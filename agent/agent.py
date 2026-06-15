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
    FOLLOW_UP_HOURS,
    ENABLE_ANALYSIS,
    FEISHU_RECEIVER_ID,
    FEISHU_RECEIVER_TYPE,
    FEISHU_WEBHOOK,
    LLM_API_KEY,
)
from feishu import FeishuClient
from cards import follow_up_card, analysis_card


def get_days_since(record: dict, client: FeishuClient) -> int:
    """从投递天数字段获取天数，或根据_record_id中的创建时间估算"""
    formula_val = client.field_value(record, "投递天数")
    if formula_val and formula_val.replace(".", "").isdigit():
        return int(float(formula_val))

    # 飞书每条记录有 create_time
    created = record.get("created_at") or record.get("created_time")
    if created:
        try:
            if "T" in str(created):
                dt = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
            else:
                dt = datetime.fromtimestamp(int(created) / 1000, tz=timezone.utc)
            return (datetime.now(timezone.utc) - dt).days
        except (ValueError, OSError):
            pass
    return 0


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

        # 2. 筛选需要提醒的记录
        pending = []
        for rec in records:
            status = client.field_value(rec, "提醒状态")
            if status not in ("", "待跟进"):
                continue
            days = get_days_since(rec, client)
            if days >= 3 or (days == 0 and FOLLOW_UP_HOURS <= 72):
                pending.append((rec, days))

        if not pending:
            print("  ✅ 没有需要跟进的记录")
            return

        print(f"  📋 {len(pending)} 条需要跟进")

        # 3. 发送跟进卡片
        store_path = os.path.join(os.path.dirname(__file__), "message_store.json")
        msg_store = {}
        if os.path.exists(store_path):
            try:
                msg_store = json.load(open(store_path))
            except (json.JSONDecodeError, OSError):
                msg_store = {}

        notify_count = 0
        for rec, days in pending:
            company = client.field_value(rec, "公司")
            position = client.field_value(rec, "岗位")
            url = client.field_value(rec, "投递链接")
            record_id = rec.get("record_id", "")

            card = follow_up_card(company, position, days, url, record_id)

            msg_id = ""
            if FEISHU_WEBHOOK:
                ok = client.send_card_via_webhook(FEISHU_WEBHOOK, card)
            elif FEISHU_RECEIVER_ID:
                msg_id = client.send_card(FEISHU_RECEIVER_ID, card, FEISHU_RECEIVER_TYPE)
                ok = bool(msg_id)
            else:
                print("  ⚠️ 未配置 FEISHU_RECEIVER_ID 或 FEISHU_WEBHOOK，跳过发送")
                print(f"    调试：{company} - {position}（{days}天）")
                ok = True

            if ok:
                notify_count += 1
                print(f"  ✅ {company} - {position}（{days}天）")
                if msg_id and record_id:
                    msg_store[record_id] = msg_id
            time.sleep(0.3)  # 限速

        # 保存 message_id 映射供回调使用
        if msg_store:
            json.dump(msg_store, open(store_path, "w"), ensure_ascii=False, indent=2)
            print(f"  💾 已保存 {len(msg_store)} 条卡片消息映射")

        print(f"\n📨 已发送 {notify_count}/{len(pending)} 条提醒")
    except Exception as e:
        print(f"  ❌ 追踪任务异常: {e}")
        raise


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

    # 提取各投递的 JD，用于分析
    jd_entries = []
    for rec in records:
        company = client.field_value(rec, "公司")
        position = client.field_value(rec, "岗位")
        jd_text = client.field_value(rec, "岗位JD")
        status = client.field_value(rec, "结果")
        remind = client.field_value(rec, "提醒状态")
        if jd_text and len(jd_text) > 20:
            jd_entries.append({
                "company": company,
                "position": position,
                "jd": jd_text[:2000],  # 截断过长的 JD
                "status": status or "投递中",
                "remind": remind,
            })

    if not jd_entries:
        print("  ⚠️ 没有足够的 JD 数据进行分析")
        return

    print(f"  📊 共 {len(jd_entries)} 个有效 JD 待分析")

    # 构造 LLM 提示
    total = len(jd_entries)
    interview = sum(1 for j in jd_entries if j["status"] in ("面试", "有反馈"))
    rejected = sum(1 for j in jd_entries if j["remind"] in ("已失效", "被拒/无反馈"))
    pending_count = total - interview - rejected

    prompt = f"""你是一个求职复盘教练。以下是用户近期投递的岗位信息汇总：

总投递数：{total}
进入面试：{interview}
被拒/无反馈：{rejected}
待跟进：{pending_count}

各岗位详情：
{chr(10).join(f"- [{j['company']}] {j['position']}: {'✅ 面试' if j['status'] in ('面试','有反馈') else '❌ 被拒' if j['remind'] in ('已失效','被拒/无反馈') else '⏳ 待跟进'} | JD: {j['jd'][:300]}" for j in jd_entries[:20])}

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


def main():
    parser = argparse.ArgumentParser(description="JobPulse Agent")
    parser.add_argument("--full", action="store_true", help="执行追踪 + 分析")
    parser.add_argument("--analyze", action="store_true", help="仅执行归因分析")
    args = parser.parse_args()

    if args.analyze:
        run_analysis()
    elif args.full:
        run_follow_up()
        if ENABLE_ANALYSIS:
            run_analysis()
    else:
        run_follow_up()


if __name__ == "__main__":
    main()
