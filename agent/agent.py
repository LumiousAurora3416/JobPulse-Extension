"""
JobPulse Agent — 求职追踪与归因分析

高频执行（日）：找出投递 ≥72h 且未跟进的记录，发送飞书跟进提醒卡片
低频归因（周）：分析 JD 特征，生成匹配度报告与投递策略建议

用法：
  python agent.py                # 执行高频追踪
  python agent.py --analyze      # 执行归因分析
  python agent.py --full         # 两个都执行
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta

from config import (
    FOLLOW_UP_FIRST_DAYS,
    FOLLOW_UP_INTERVAL_DAYS,
    FOLLOW_UP_MAX_CARDS,
    ENABLE_ANALYSIS,
    FEISHU_RECEIVER_ID,
    FEISHU_RECEIVER_TYPE,
    FEISHU_WEBHOOK,
    LLM_API_KEY,
)
from feishu import FeishuClient
from cards import follow_up_card, analysis_card, stats_card, interview_reminder_card
from status_rules import (
    RESULT_LOST,
    RESULT_OFFER,
    RESULT_QUIET,
    is_terminal,
    should_remind,
)


def _parse_ts_ms(ts):
    """Parse various timestamp/date formats to ms since epoch. Returns None on failure."""
    if not ts:
        return None
    if isinstance(ts, (int, float)):
        ts = int(ts)
        # Heuristic: 1e9~1e11 范围大概率是秒级时间戳，转成毫秒
        if 1_000_000_000 <= ts < 100_000_000_000:
            ts = ts * 1000
        return ts
    if isinstance(ts, str):
        ts = ts.strip()
        if ts.isdigit():
            val = int(ts)
            if 1_000_000_000 <= val < 100_000_000_000:
                val = val * 1000
            return val
        try:
            dt = datetime.strptime(ts[:10], "%Y-%m-%d")
            return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)
        except (ValueError, IndexError):
            pass
    return None


def get_days_since(record: dict, client: FeishuClient) -> int:
    """从投递天数字段获取天数，或根据 record 创建时间估算。
    无法确定时返回 999（宁可多提醒不漏提醒）"""
    formula_val = client.field_value(record, "投递天数")
    if formula_val and formula_val.replace(".", "").isdigit():
        return int(float(formula_val))

    # Fallback: fields.投递时间 > record created_time/created_at
    fields = record.get("fields", {})
    ts = fields.get("投递时间") or record.get("created_time") or record.get("created_at")
    if ts:
        ct = _parse_ts_ms(ts)
        if ct:
            dt = datetime.fromtimestamp(ct / 1000, tz=timezone.utc)
            return (datetime.now(timezone.utc) - dt).days
    return 999  # fallback: 无法确定天数时默认需要跟进


def _today_start_ms() -> int:
    """今天 00:00 的毫秒时间戳（日期字段写当天零点，便于按天算间隔）。"""
    now = datetime.now()
    return int(datetime(now.year, now.month, now.day).timestamp() * 1000)


def get_days_since_last_remind(record: dict, client: FeishuClient):
    """距上次提醒的天数；从没提醒过返回 None（排序时最优先）。

    提醒节奏完全由本字段驱动——「提醒状态」已改为公式列（只给人看，代码不读不写）。
    """
    ts = _parse_ts_ms(record.get("fields", {}).get("上次提醒日期"))
    if not ts:
        return None
    return (time.time() * 1000 - ts) / 86400000


def run_follow_up():
    """高频追踪：找出待跟进的记录并发送卡片"""
    print("=" * 50)
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] 追踪任务开始")

    try:
        client = FeishuClient()

        # 1. 获取所有记录
        print("📡 查询飞书表格...")
        try:
            records = client.list_records()
        except RuntimeError as e:
            print(f"  ❌ {e}")
            return
        print(f"  ✅ 共 {len(records)} 条记录")

        # 2. 筛选候选：结果处于「会被催的过程态」，且满足首次/复催的时间门槛。
        #    「是否继续提醒」完全由结果推导（终态即停），不再依赖手工标 提醒状态
        candidates = []
        for rec in records:
            result = client.field_value(rec, "结果")
            if not should_remind(result):
                continue  # 终态（挂/offer/无反馈/放弃）与「待投递」都不催
            days = get_days_since(rec, client)
            if days < FOLLOW_UP_FIRST_DAYS:
                continue  # 太早跟进没意义：简历可能还没被处理
            since_last = get_days_since_last_remind(rec, client)
            if since_last is not None and since_last < FOLLOW_UP_INTERVAL_DAYS:
                continue  # 复催间隔没到，先不打扰
            candidates.append((rec, days, since_last))

        if not candidates:
            print("  ✅ 没有需要跟进的记录")
            return

        # 最久没催的排最前（从没催过 = None → 视为最优先）；同为"从没催过"时，
        # 再按投递天数从大到小排——否则一大批"从没催过"会并列，名次实际由记录顺序决定
        candidates.sort(key=lambda c: (c[2] is not None, -(c[2] or 0), -c[1]))
        pending = candidates[:FOLLOW_UP_MAX_CARDS]
        print(f"  📋 {len(candidates)} 条待跟进，本次推送 {len(pending)} 条（上限 {FOLLOW_UP_MAX_CARDS}）")

        # 3. 发送跟进卡片
        store_path = os.path.join(os.path.dirname(__file__), "message_store.json")
        msg_store = {}
        if os.path.exists(store_path):
            try:
                msg_store = json.load(open(store_path))
            except (json.JSONDecodeError, OSError):
                msg_store = {}

        notify_count = 0
        today_ms = _today_start_ms()
        for rec, days, _since_last in pending:
            company = client.field_value(rec, "公司")
            position = client.field_value(rec, "岗位")
            url = client.field_value(rec, "投递链接")
            result = client.field_value(rec, "结果")
            record_id = rec.get("record_id", "")

            # 按钮按当前结果动态生成（卡片在哪个阶段就只给这个阶段可能的下一步）
            card = follow_up_card(company, position, days, url, record_id, result)

            msg_id = ""
            delivered = False
            if FEISHU_WEBHOOK:
                delivered = bool(client.send_card_via_webhook(FEISHU_WEBHOOK, card))
            elif FEISHU_RECEIVER_ID:
                msg_id = client.send_card(FEISHU_RECEIVER_ID, card, FEISHU_RECEIVER_TYPE)
                delivered = bool(msg_id)
            else:
                print("  ⚠️ 未配置 FEISHU_RECEIVER_ID 或 FEISHU_WEBHOOK，跳过发送")
                print(f"    调试：{company} - {position}（{days}天）")

            if delivered:
                notify_count += 1
                print(f"  ✅ {company} - {position}（{days}天，{result}）")
                if record_id:
                    # 只有真发出去了才记「上次提醒日期」，否则下一轮仍会重试
                    patch = {"上次提醒日期": today_ms}
                    if msg_id:
                        msg_store[record_id] = msg_id
                        patch["消息ID"] = msg_id  # 回调时可直接从记录读取
                    client.update_record(record_id, patch)
            time.sleep(0.3)  # 限速

        # 保存 message_id 映射供回调使用
        if msg_store:
            json.dump(msg_store, open(store_path, "w"), ensure_ascii=False, indent=2)
            print(f"  💾 已保存 {len(msg_store)} 条卡片消息映射")

        print(f"\n📨 已发送 {notify_count}/{len(pending)} 条提醒")
    except Exception as e:
        print(f"  ❌ 追踪任务异常: {e}")
        raise


def _entry_mark(status: str) -> str:
    """归因提示里给每条投递配个进度标记（全部取自「结果」列的取值）。"""
    if status in RESULT_OFFER:
        return "🎉 offer"
    if status == "面试":
        return "✅ 面试中"
    if status in RESULT_LOST:
        return "❌ 被拒"
    if status in RESULT_QUIET:
        return "📋 无结论结束"
    return "⏳ 进行中"


def run_analysis():
    """低频归因分析"""
    if not LLM_API_KEY:
        print("  ⚠️ 未配置 LLM_API_KEY，跳过归因分析")
        return

    print(f"\n[{datetime.now():%Y-%m-%d %H:%M}] 归因分析开始")

    client = FeishuClient()
    try:
        records = client.list_records()
    except RuntimeError as e:
        print(f"  ❌ {e}")
        return

    # 提取各投递的 JD，用于分析（排除"待投递"状态）
    jd_entries = []
    for rec in records:
        company = client.field_value(rec, "公司")
        position = client.field_value(rec, "岗位")
        jd_text = client.field_value(rec, "岗位JD")
        status = client.field_value(rec, "结果")
        if status == "待投递":
            continue
        if jd_text and len(jd_text) > 20:
            jd_entries.append({
                "company": company,
                "position": position,
                "jd": jd_text[:2000],  # 截断过长的 JD
                "status": status,
            })

    if not jd_entries:
        print("  ⚠️ 没有足够的 JD 数据进行分析")
        return

    print(f"  📊 共 {len(jd_entries)} 个有效 JD 待分析")

    # 构造 LLM 提示（统计全部按「结果」状态机；原实现拿结果列的值去比提醒状态的取值，恒为 0）
    total = len(jd_entries)
    interview = sum(1 for j in jd_entries if j["status"] == "面试")
    rejected = sum(1 for j in jd_entries if j["status"] in RESULT_LOST)
    offered = sum(1 for j in jd_entries if j["status"] in RESULT_OFFER)
    quiet = sum(1 for j in jd_entries if j["status"] in RESULT_QUIET)
    pending_count = total - interview - rejected - offered - quiet

    prompt = f"""你是一个求职复盘教练。以下是用户近期投递的岗位信息汇总：

总投递数：{total}
面试中：{interview}
被拒（挂）：{rejected}
已拿 offer：{offered}
无结论结束（无反馈/放弃）：{quiet}
仍在进行：{pending_count}

各岗位详情：
{chr(10).join(f"- [{j['company']}] {j['position']}: {_entry_mark(j['status'])} | JD: {j['jd'][:300]}" for j in jd_entries[:20])}

请从以下三个方面给出分析（控制在 800 字以内，用中文）：
1. **投递画像**：投递的行业/岗位分布特征
2. **JD 要求关键词提取**：这些岗位共同要求哪些技能/经验
3. **策略建议**：下一步应该优化简历的哪些方向、优先投递什么类型的岗位
"""

    print("  🤖 调用 LLM 分析...")
    try:
        if "anthropic" in LLM_API_KEY or LLM_API_BASE:
            pass
        from llm_client import LLMClient
        llm = LLMClient()
        result = llm.chat(prompt)

        # 4. 发送分析结果卡片
        insights = result.get("insights", [result.get("text", "分析完成")])
        summary = result.get("summary", f"本周共分析 {total} 个投递，其中 {interview} 个获得面试机会。")

        card = analysis_card(summary, insights)

        if FEISHU_RECEIVER_ID:
            client.send_card(FEISHU_RECEIVER_ID, card, FEISHU_RECEIVER_TYPE)
        elif FEISHU_WEBHOOK:
            client.send_card_via_webhook(FEISHU_WEBHOOK, card)
        else:
            print(f"\n📊 分析结果预览：\n{summary}")
            for ins in insights:
                print(f"  • {ins}")

        print("  ✅ 归因分析完成")

    except Exception as e:
        print(f"  ❌ LLM 分析失败: {e}")


def run_statistics():
    """数据统计：统计投递总量、面试数、待跟进数等，发送统计卡片"""
    print("=" * 50)
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] 数据统计任务开始")

    client = FeishuClient()
    try:
        records = client.list_records()
    except RuntimeError as e:
        print(f"  ❌ {e}")
        return

    total = len(records)
    if total == 0:
        print("  ⚠️ 表格为空，无数据可统计")
        return

    # 按「结果」状态机分桶（不再读已废弃的 提醒状态）
    to_apply = in_progress = offered = lost = quiet = unknown = 0

    for rec in records:
        result = client.field_value(rec, "结果")
        if result == "待投递":
            to_apply += 1
        elif result in RESULT_OFFER:
            offered += 1
        elif result in RESULT_LOST:
            lost += 1
        elif result in RESULT_QUIET:
            quiet += 1
        elif should_remind(result):
            in_progress += 1
        else:
            unknown += 1  # 空值/未定义值：单独计出来，便于发现脏数据

    print(f"  📊 投递 {total} | 待投递 {to_apply} | 进行中 {in_progress} | offer {offered} | 已挂 {lost} | 无结论 {quiet}"
          + (f" | ⚠️ 未识别 {unknown}" if unknown else ""))

    card = stats_card(total, to_apply, in_progress, offered, lost, quiet)

    if FEISHU_RECEIVER_ID:
        ok = client.send_card(FEISHU_RECEIVER_ID, card, FEISHU_RECEIVER_TYPE)
        if ok:
            print("  ✅ 统计卡片已发送")
        else:
            print("  ❌ 统计卡片发送失败")
    elif FEISHU_WEBHOOK:
        ok = client.send_card_via_webhook(FEISHU_WEBHOOK, card)
        if ok:
            print("  ✅ 统计卡片已发送")
        else:
            print("  ❌ 统计卡片发送失败")
    else:
        print(f"\n📈 统计预览：投递 {total} | 待投递 {to_apply} | 进行中 {in_progress} | offer {offered} ({offered / total * 100:.1f}%) | 已挂 {lost} | 无结论 {quiet}")


def run_interview_reminder():
    """面试日程提醒：查询面试时间在未来1-2天的记录，发送提醒卡片"""
    print("=" * 50)
    print(f"[{datetime.now():%Y-%m-%d %H:%M}] 面试提醒任务开始")

    client = FeishuClient()
    try:
        records = client.list_records()
    except RuntimeError as e:
        print(f"  ❌ {e}")
        return

    # 筛选有面试时间的记录
    upcoming = []
    for rec in records:
        interview_date = client.field_value(rec, "面试时间")
        if not interview_date:
            continue
        try:
            # 飞书日期格式通常是 "YYYY-MM-DD" 或时间戳
            dt = None
            if isinstance(interview_date, (int, float)):
                dt = datetime.fromtimestamp(int(interview_date) / 1000, tz=timezone.utc)
            elif isinstance(interview_date, str):
                dt = datetime.strptime(interview_date, "%Y-%m-%d")
            else:
                dt = datetime.fromisoformat(str(interview_date).replace("Z", "+00:00"))

            days_diff = (dt.date() - datetime.now(timezone.utc).date()).days
            if 0 <= days_diff <= 2:
                company = client.field_value(rec, "公司")
                position = client.field_value(rec, "岗位")
                upcoming.append({
                    "company": company,
                    "position": position,
                    "date": interview_date,
                    "days": days_diff,
                })
        except (ValueError, OSError):
            continue

    if not upcoming:
        print("  ✅ 没有即将到来的面试")
        return

    print(f"  📅 发现 {len(upcoming)} 个即将面试")

    for item in upcoming:
        card = interview_reminder_card(item["company"], item["position"], str(item["date"]))
        if FEISHU_RECEIVER_ID:
            client.send_card(FEISHU_RECEIVER_ID, card, FEISHU_RECEIVER_TYPE)
        elif FEISHU_WEBHOOK:
            client.send_card_via_webhook(FEISHU_WEBHOOK, card)
        else:
            print(f"  ⏰ {item['company']} - {item['position']} @ {item['date']}（{item['days']}天后）")
        time.sleep(0.3)

    print(f"  ✅ 已发送 {len(upcoming)} 条面试提醒")


def run_match(jd_path: str, resume_path: str):
    """--match：岗位匹配度评分（JD + 简历 → 评分报告，见 docs/match-schema.md）"""
    if not LLM_API_KEY:
        print("  ❌ 未配置 LLM_API_KEY，无法评分")
        return
    if not jd_path or not resume_path:
        print("  ⚠️ 请提供 --jd <JD文件> --resume <简历文件>")
        return
    try:
        jd_text = open(jd_path, encoding="utf-8").read()
        resume_text = open(resume_path, encoding="utf-8").read()
    except OSError as e:
        print(f"  ❌ 读取文件失败: {e}")
        return

    from match_engine import evaluate
    report = evaluate(jd_text, resume_text)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="JobPulse Agent")
    parser.add_argument("--full", action="store_true", help="执行追踪 + 分析")
    parser.add_argument("--analyze", action="store_true", help="仅执行归因分析")
    parser.add_argument("--stats", action="store_true", help="仅执行数据统计")
    parser.add_argument("--match", action="store_true", help="岗位匹配度评分（配 --jd --resume）")
    parser.add_argument("--jd", help="岗位 JD 文本文件路径")
    parser.add_argument("--resume", help="简历文本文件路径")
    args = parser.parse_args()

    if args.match:
        run_match(args.jd, args.resume)
    elif args.stats:
        run_statistics()
    elif args.analyze:
        run_analysis()
    elif args.full:
        run_follow_up()
        if ENABLE_ANALYSIS:
            run_analysis()
    else:
        run_follow_up()


if __name__ == "__main__":
    main()
