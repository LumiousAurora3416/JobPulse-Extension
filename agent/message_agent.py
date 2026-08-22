"""
JobPulse Message Agent — 处理用户私聊消息（Agent 化）

核心流程：LLM 自主决定调用工具（function calling）→ 执行 → 结果回填 → LLM 自然语言回复
- 支持多轮对话记忆（memory.py）
- 若 API 不支持 function calling，自动降级到旧 classify 路径（_fallback_reply）

入口保持 handle_message(sender_id, message_text, receive_id_type="open_id") 不变，
callback_server.py 无需改动。
"""

import json
import re
import time
from datetime import datetime, timezone, timedelta

from feishu import FeishuClient
from llm_client import LLMClient
from cards import follow_up_card
from config import FOLLOW_UP_HOURS
from memory import append_turn, get_history
from profile import get_profile, upsert_facts, format_profile


# ── Agent 系统提示词（function calling 模式） ──────────────────

AGENT_SYSTEM_PROMPT = """你是 JobPulse 求职投递助手，帮助用户在飞书多维表格里管理求职投递记录。
当前日期：{today}

# 你的能力
你可以调用工具查询、录入、更新投递数据。数据存储在飞书多维表格，字段包括：
- 公司、岗位、岗位JD、投递链接、薪资
- 结果：待投递 / 简历 / 面试 / 无反馈 / 简历挂
- 提醒状态：待跟进 / 已跟进 / 已失效 / 有反馈
- 投递天数、面试时间

# 使用规则
1. 用户想查/记/改投递数据时，先判断该调用哪个工具，把参数提取成工具要求的格式再调用。
2. 工具返回的是结构化数据，你要用自然语言、口语化中文组织成友好回复，不要暴露工具名或字段名。
3. 缺参数时，先用一句话向用户追问补充（如「请问是哪个公司？」），不要瞎猜；用户补上后再调用工具。
4. 公司名支持模糊匹配，用户说「字节」「字节跳动」都应能查到。
5. 涉及具体日期时，以当前日期 {today} 为基准换算「昨天」「后天」等说法。
6. 用户只是闲聊、打招呼、道谢，或意图不明确时，直接自然回复即可，不要调用工具。
7. 查询结果为空时，如实说明，并给用户下一步建议。

# 长期记忆
- 用户提到的长期偏好/背景（主要投什么方向、所在城市、技能栈、工作年限等）用 save_memory 记住，跨会话保留。
- 需要结合用户背景回答（如推荐投递方向、给建议）时，先调用 recall_memory 取回画像。
- 不要用 save_memory 记录一次性事件（如「今天投了字节」）。
"""

# 旧意图分类提示词（仅作降级路径保留）
OLD_SYSTEM_PROMPT = """你是一个求职投递助手，用户在飞书多维表格里记录投递进度。
当前日期：{today}

请把用户的发言分类到以下**一个**意图中，返回纯 JSON（不要 markdown）。

意图列表：

- query_today_count：问今天投了多少、投了哪些
  例如："今天投了多少" "今天投了哪些" "今天投了啥"
- query_date_count：问某一天或某个时间段的投递记录（昨天、前天、某月某日）
  例如："昨天投了多少" "昨天投了哪些" "前天投递" "7月8号投了啥"
  ⚠️ "今天"相关用 query_today_count，不要分到这里
  提取参数：date_ref（日期描述，必填，例如"昨天""前天""7月8号"）

- query_pending：问哪些没反馈、待跟进的
  例如："哪些没反馈" "待跟进" "哪些还没消息" "还没回应的"

- query_interviews：问面试安排、最近面试时间
  例如："面试安排" "最近面试" "什么时候面试"

- query_statistics：问投递统计数据、总量
  例如："统计数据" "投递情况" "一共投了多少" "有多少面试"

- query_record：查某家公司的投递进度（该公司已存在表格中）
  例如："我投的字节怎么样了" "腾讯那个岗位有消息吗" "阿里云现在什么情况"
  提取参数：company（公司名，必填）、position（岗位名，可选）

- record_interview：记录或更新面试时间
  例如："字节周三下午两点面试" "腾讯后天上午十点面试" "帮我记下面试时间"
  提取参数：company（公司名，必填）、interview_time（面试时间，必填，格式 YYYY-MM-DD HH:MM，UTC+8）、position（岗位名，可选）

- create_record：录入一条新投递记录。用户可能会简单带一句职位描述或要求
  例如："投了字节前端" "刚在Boss投了快手" "记一下我投了腾讯" "投了阿里云算法岗，主要做推荐系统" "今天投了美团后端，JD要熟悉Go和微服务"
  ⚠️ 如果用户是问已有记录的状态，用 query_record，不要用 create_record
  提取参数：company（公司名）、position（岗位名）、platform（平台名，可选）、jd（岗位描述/要求文本，可选，提取职位名称后面描述职责或要求的那部分内容）

- update_status：更新某家公司的投递状态
  例如："腾讯有反馈了" "改成面试" "字节挂了" "美团有消息了"
  提取参数：company（公司名）、new_status（面试/无反馈/简历挂/已跟进）

- trigger_follow_up：手动推送跟进提醒卡片
  例如："推送卡片" "发送提醒" "推送跟进" "发跟进卡片" "推送"

- chat：打招呼、感谢、闲聊、看不出来意图、或以上都不匹配

返回格式：
{{"intent": "意图名称", "params": {{...}}}}
"""

# 兜底引导文案（意图不明 / 闲聊）
HELP_TEXT = (
    "你好！我可以帮你：\n"
    "📋 查询今天投递：「今天投了多少」\n"
    "📅 查询某天投递：「昨天投了啥」\n"
    "⏳ 查看待跟进：「哪些没反馈」\n"
    "📅 面试安排：「最近面试」\n"
    "📊 投递统计：「统计数据」\n"
    "🔍 查投递进度：「字节怎么样了」\n"
    "✏️ 记录新投递：「投了字节前端」\n"
    "🔄 更新状态：「腾讯有反馈了」\n"
    "📅 记录面试时间：「字节周三面试」\n"
    "📨 推送跟进卡片：「推送卡片」\n\n"
    "试试看吧！"
)


# ── 工具层（返回结构化 dict，由 LLM 决定调用） ─────────────────

def _query_today_count(ctx, **kwargs) -> dict:
    """查询今天投递的公司岗位。"""
    client = ctx["client"]
    tz8 = timezone(timedelta(hours=8))
    now = datetime.now(tz8)
    today_start = datetime(now.year, now.month, now.day, tzinfo=tz8)
    today_end = today_start + timedelta(days=1)
    start_ms = int(today_start.timestamp() * 1000)
    end_ms = int(today_end.timestamp() * 1000)

    items = []
    for rec in client.list_records():
        fields = rec.get("fields", {})
        ts = fields.get("投递时间") or rec.get("created_time") or rec.get("created_at", 0)
        if not ts:
            continue
        ct = _parse_ts_ms(ts, tz8)
        if ct and start_ms <= ct < end_ms:
            company = client.field_value(rec, "公司")
            position = client.field_value(rec, "岗位")
            items.append({
                "company": company,
                "position": position,
                "label": f"{company} - {position}" if company else (position or "未命名"),
            })
    return {"ok": True, "count": len(items), "items": items}


def _query_date_count(ctx, **kwargs) -> dict:
    """查询某一天/某时间段的投递记录。"""
    client = ctx["client"]
    date_ref = (kwargs.get("date_ref") or "").strip()
    if not date_ref:
        return {"ok": False, "error": "你想查哪天的投递？比如「昨天投了啥」「前天投递」"}

    tz8 = timezone(timedelta(hours=8))
    now = datetime.now(tz8)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    target = None
    label = date_ref
    ref = date_ref

    if ref in ("昨天", "昨日"):
        target = today - timedelta(days=1)
        label = "昨天"
    elif ref in ("前天", "前日"):
        target = today - timedelta(days=2)
        label = "前天"
    elif re.match(r"^\d{4}-\d{2}-\d{2}$", ref):
        try:
            target = datetime.strptime(ref, "%Y-%m-%d").replace(tzinfo=tz8)
            label = ref
        except ValueError:
            pass
    elif "月" in ref and ("号" in ref or "日" in ref):
        m = re.match(r"(\d{1,2})月(\d{1,2})[号日]", ref)
        if m:
            target = today.replace(month=int(m.group(1)), day=int(m.group(2)))
            label = ref

    if target is None:
        return {"ok": False, "error": f"没看明白「{date_ref}」是哪天，试试说「昨天投了多少」「前天投递」"}

    start_ms = int(target.timestamp() * 1000)
    end_ms = int((target + timedelta(days=1)).timestamp() * 1000)

    items = []
    for rec in client.list_records():
        fields = rec.get("fields", {})
        ts = fields.get("投递时间") or rec.get("created_time") or rec.get("created_at", 0)
        if not ts:
            continue
        ct = _parse_ts_ms(ts, tz8)
        if ct and start_ms <= ct < end_ms:
            company = client.field_value(rec, "公司")
            position = client.field_value(rec, "岗位")
            items.append({
                "company": company,
                "position": position,
                "label": f"{company} - {position}" if company else (position or "未命名"),
            })
    return {"ok": True, "date": label, "count": len(items), "items": items}


def _query_pending(ctx, **kwargs) -> dict:
    """查询待跟进（无反馈）的投递。"""
    client = ctx["client"]
    pending = []
    for rec in client.list_records():
        status = client.field_value(rec, "提醒状态")
        result = client.field_value(rec, "结果")
        if status == "待跟进" and result != "待投递":
            pending.append({
                "company": client.field_value(rec, "公司") or "未知",
                "position": client.field_value(rec, "岗位") or "未知",
                "days": client.field_value(rec, "投递天数"),
            })
    return {"ok": True, "count": len(pending), "items": pending}


def _query_interviews(ctx, **kwargs) -> dict:
    """查询面试安排：已进入面试阶段的岗位，含/不含面试时间。"""
    client = ctx["client"]
    interviews = []
    no_date = []
    for rec in client.list_records():
        result = client.field_value(rec, "结果")
        interview_date = client.field_value(rec, "面试时间")
        if result != "面试" and not interview_date:
            continue
        company = client.field_value(rec, "公司")
        position = client.field_value(rec, "岗位")
        label = f"{company or '未知'} - {position or '未知'}"
        if interview_date:
            interviews.append({"label": label, "date": str(interview_date)})
        else:
            no_date.append(label)
    return {"ok": True, "count": len(interviews), "interviews": interviews, "no_date": no_date}


def _query_statistics(ctx, **kwargs) -> dict:
    """聚合投递统计。"""
    client = ctx["client"]
    records = client.list_records()
    total = len(records)
    if total == 0:
        return {"ok": True, "total": 0, "empty": True}
    to_apply = sum(1 for r in records if client.field_value(r, "结果") == "待投递")
    interview = sum(1 for r in records if client.field_value(r, "结果") == "面试")
    pending = sum(1 for r in records if client.field_value(r, "提醒状态") == "待跟进")
    followed = sum(1 for r in records if client.field_value(r, "提醒状态") == "已跟进")
    lost = sum(1 for r in records if client.field_value(r, "提醒状态") in ("已失效", "被拒/无反馈"))
    rate = round(interview / total * 100, 1) if total else 0
    return {
        "ok": True, "total": total, "to_apply": to_apply, "interview": interview,
        "interview_rate": rate, "pending": pending, "followed": followed, "lost": lost,
    }


def _query_record(ctx, **kwargs) -> dict:
    """查询某家公司的投递进度（支持模糊匹配）。"""
    client = ctx["client"]
    company = kwargs.get("company", "") or ""
    position = kwargs.get("position", "") or ""
    if not company:
        return {"ok": False, "error": "你想查哪家公司的投递情况？说清楚公司名就行"}

    matches = []
    for rec in client.list_records():
        c = client.field_value(rec, "公司")
        if c == company or (company in c or c in company):
            matches.append({
                "company": c,
                "position": client.field_value(rec, "岗位"),
                "result": client.field_value(rec, "结果"),
                "status": client.field_value(rec, "提醒状态"),
                "days": client.field_value(rec, "投递天数"),
                "interview_date": client.field_value(rec, "面试时间"),
            })
    return {"ok": True, "company": company, "position_hint": position, "total": len(matches), "matches": matches}


def _record_interview(ctx, **kwargs) -> dict:
    """记录/更新某家公司的面试时间，同时把结果置为「面试」、状态置为「有反馈」。"""
    client = ctx["client"]
    company = kwargs.get("company", "") or ""
    interview_time = kwargs.get("interview_time", "") or ""
    position = kwargs.get("position", "") or ""

    if not company:
        return {"ok": False, "error": "你说的是哪家公司？比如「字节周三下午两点面试」"}
    if not interview_time:
        return {"ok": False, "error": "面试时间是什么时候？比如「字节周三下午两点面试」"}

    tz8 = timezone(timedelta(hours=8))
    try:
        dt = datetime.strptime(interview_time, "%Y-%m-%d %H:%M").replace(tzinfo=tz8)
        time_ms = int(dt.timestamp() * 1000)
    except ValueError:
        return {"ok": False, "error": f"时间「{interview_time}」我没看懂，直接跟我说「字节周三下午两点面试」就好"}

    records = client.list_records()
    target = None
    target_position = ""
    for rec in records:
        c = client.field_value(rec, "公司")
        p = client.field_value(rec, "岗位")
        if c == company or (company in c or c in company):
            if position and p == position:
                target = rec
                target_position = p
                break
            elif not position and target is None:
                target = rec
                target_position = p

    if not target:
        return {"ok": False, "error": f"没找到「{company}」的投递记录"}

    record_id = target.get("record_id", "")
    fields = {"面试时间": time_ms, "结果": "面试", "提醒状态": "有反馈"}
    ok = client.update_record(record_id, fields)
    if not ok:
        return {"ok": False, "error": "更新失败，请稍后重试"}

    time_str = dt.strftime("%Y年%m月%d日 %H:%M")
    pos_str = f"（{target_position}）" if target_position else ""
    return {"ok": True, "message": f"已记录 {company}{pos_str} 面试时间：{time_str}"}


def _execute_create(ctx, **kwargs) -> dict:
    """录入一条新投递记录（含去重检查）。"""
    client = ctx["client"]
    company = kwargs.get("company", "") or ""
    position = kwargs.get("position", "") or ""
    platform = kwargs.get("platform", "") or ""
    jd = kwargs.get("jd", "") or ""

    if not company and not position:
        return {"ok": False, "error": "没识别到公司和岗位信息，麻烦说清楚一些，比如「我在Boss投了字节前端」"}

    # 去重：完全同公司+岗位则提示，避免误录入
    if company and position:
        for rec in client.list_records():
            existing_company = client.field_value(rec, "公司")
            existing_position = client.field_value(rec, "岗位")
            if existing_company == company and existing_position == position:
                existing_status = client.field_value(rec, "结果")
                return {
                    "ok": False, "duplicate": True, "company": company, "position": position,
                    "existing_status": existing_status or "未更新",
                }

    today = datetime.now()
    today_ms = int(datetime(today.year, today.month, today.day).timestamp() * 1000)
    fields = {
        "公司": company,
        "岗位": position,
        "岗位JD": jd,
        "结果": "简历",
        "提醒状态": "待跟进",
        "投递时间": today_ms,
    }
    record_id = client.create_record(fields)
    if not record_id:
        return {"ok": False, "error": "创建失败，请稍后重试"}

    missing = []
    if not company:
        missing.append("公司名")
    if not position:
        missing.append("岗位名")
    return {"ok": True, "company": company, "position": position, "platform": platform,
            "jd_saved": bool(jd), "missing": missing}


def _execute_update(ctx, **kwargs) -> dict:
    """更新某家公司的投递状态。"""
    client = ctx["client"]
    valid_statuses = ("面试", "无反馈", "简历挂", "已跟进")
    company = kwargs.get("company", "") or ""
    new_status = kwargs.get("new_status", "") or ""

    if not company:
        return {"ok": False, "error": "没识别到是哪家公司，请说清楚公司名"}
    if new_status not in valid_statuses:
        return {"ok": False, "error": f"支持的状态：{'、'.join(valid_statuses)}。你说是哪一种？"}

    target = None
    for rec in client.list_records():
        if client.field_value(rec, "公司") == company:
            target = rec
            break
    if not target:
        return {"ok": False, "error": f"没找到「{company}」的投递记录"}

    record_id = target.get("record_id", "")
    if not record_id:
        return {"ok": False, "error": "无法获取记录 ID"}

    fields = {"提醒状态": new_status}
    if new_status == "面试":
        fields["结果"] = "面试"

    ok = client.update_record(record_id, fields)
    if not ok:
        return {"ok": False, "error": "更新失败，请稍后重试"}
    return {"ok": True, "message": f"已将「{company}」更新为「{new_status}」"}


def _trigger_follow_up(ctx, **kwargs) -> dict:
    """手动推送所有待跟进投递的跟进提醒卡片。"""
    client = ctx["client"]
    sender_id = ctx["sender_id"]
    receive_id_type = ctx["receive_id_type"]
    threshold_days = FOLLOW_UP_HOURS / 24

    pending = []
    for rec in client.list_records():
        result = client.field_value(rec, "结果")
        if result == "待投递":
            continue
        status = client.field_value(rec, "提醒状态")
        if status not in ("", "待跟进"):
            continue
        days = _get_days(rec, client)
        if days >= threshold_days:
            company = client.field_value(rec, "公司")
            position = client.field_value(rec, "岗位")
            url = client.field_value(rec, "投递链接")
            record_id = rec.get("record_id", "")
            pending.append((company, position, days, url, record_id))

    if not pending:
        return {"ok": True, "count": 0, "sent": 0}

    sent = 0
    for company, position, days, url, record_id in pending:
        card = follow_up_card(company, position, days, url, record_id)
        msg_id = client.send_card(sender_id, card, receive_id_type)
        if msg_id:
            client.update_record(record_id, {"消息ID": msg_id})
            sent += 1
        time.sleep(0.3)

    return {"ok": True, "count": len(pending), "sent": sent}


def _save_memory(ctx, **kwargs) -> dict:
    """记住用户长期偏好（跨会话保留）。"""
    sender_id = ctx["sender_id"]
    facts = kwargs.get("facts") or []
    valid = [f for f in facts
             if (f.get("key") or "").strip() and (f.get("value") or "").strip()]
    if not valid:
        return {"ok": False, "error": "没有要记住的内容，告诉我你的偏好，比如「我主要投前端」"}
    profile = upsert_facts(sender_id, valid)
    return {"ok": True, "saved": len(valid), "profile": profile}


def _recall_memory(ctx, **kwargs) -> dict:
    """取回用户长期偏好画像。"""
    sender_id = ctx["sender_id"]
    entry = get_profile(sender_id)
    profile = entry.get("profile") or {}
    return {"ok": True, "has_profile": bool(profile), "profile": profile,
            "summary": format_profile(profile)}


# ── 工具注册表（LLM 可见的 function schema） ────────────────────

TOOLS: dict[str, dict] = {
    "query_today_count": {
        "function": _query_today_count,
        "schema": {"type": "function", "function": {
            "name": "query_today_count",
            "description": "查询今天投递了多少份简历、投了哪些公司岗位",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }},
    },
    "query_date_count": {
        "function": _query_date_count,
        "schema": {"type": "function", "function": {
            "name": "query_date_count",
            "description": "查询某一天或某时间段的投递记录，支持「昨天」「前天」「7月8号」等说法",
            "parameters": {"type": "object",
                "properties": {"date_ref": {"type": "string", "description": "日期描述，如 昨天/前天/7月8号"}},
                "required": ["date_ref"]},
        }},
    },
    "query_pending": {
        "function": _query_pending,
        "schema": {"type": "function", "function": {
            "name": "query_pending",
            "description": "查询哪些投递还没反馈、需要跟进",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }},
    },
    "query_interviews": {
        "function": _query_interviews,
        "schema": {"type": "function", "function": {
            "name": "query_interviews",
            "description": "查询面试安排：哪些岗位已进入面试、各自的面试时间",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }},
    },
    "query_statistics": {
        "function": _query_statistics,
        "schema": {"type": "function", "function": {
            "name": "query_statistics",
            "description": "查询投递统计数据：总量、待投递、面试数、待跟进等",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }},
    },
    "query_record": {
        "function": _query_record,
        "schema": {"type": "function", "function": {
            "name": "query_record",
            "description": "查某家公司的投递进度，支持模糊匹配公司名（如 字节、腾讯、阿里云）",
            "parameters": {"type": "object",
                "properties": {
                    "company": {"type": "string", "description": "公司名，如 字节/腾讯/阿里云"},
                    "position": {"type": "string", "description": "岗位名，可选"},
                },
                "required": ["company"]},
        }},
    },
    "record_interview": {
        "function": _record_interview,
        "schema": {"type": "function", "function": {
            "name": "record_interview",
            "description": "记录或更新某家公司的面试时间，同时自动把结果置为「面试」",
            "parameters": {"type": "object",
                "properties": {
                    "company": {"type": "string", "description": "公司名，如 字节"},
                    "interview_time": {"type": "string", "description": "面试时间，格式 YYYY-MM-DD HH:MM，如 2026-08-25 14:00"},
                    "position": {"type": "string", "description": "岗位名，可选"},
                },
                "required": ["company", "interview_time"]},
        }},
    },
    "create_record": {
        "function": _execute_create,
        "schema": {"type": "function", "function": {
            "name": "create_record",
            "description": "录入一条新的投递记录（用户刚投了某家公司某个岗位），可带平台名和岗位JD描述",
            "parameters": {"type": "object",
                "properties": {
                    "company": {"type": "string", "description": "公司名，如 字节"},
                    "position": {"type": "string", "description": "岗位名，如 前端工程师"},
                    "platform": {"type": "string", "description": "投递平台，可选，如 Boss/官网"},
                    "jd": {"type": "string", "description": "岗位JD描述/要求文本，可选"},
                },
                "required": []},
        }},
    },
    "update_status": {
        "function": _execute_update,
        "schema": {"type": "function", "function": {
            "name": "update_status",
            "description": "更新某家公司的投递状态（有反馈了/进面试/挂了等）",
            "parameters": {"type": "object",
                "properties": {
                    "company": {"type": "string", "description": "公司名，如 腾讯"},
                    "new_status": {"type": "string",
                        "description": "新状态，只能是以下之一：面试 / 无反馈 / 简历挂 / 已跟进",
                        "enum": ["面试", "无反馈", "简历挂", "已跟进"]},
                },
                "required": ["company", "new_status"]},
        }},
    },
    "trigger_follow_up": {
        "function": _trigger_follow_up,
        "schema": {"type": "function", "function": {
            "name": "trigger_follow_up",
            "description": "手动推送所有待跟进投递的跟进提醒卡片",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }},
    },
    "save_memory": {
        "function": _save_memory,
        "schema": {"type": "function", "function": {
            "name": "save_memory",
            "description": "记住用户长期偏好或背景信息，跨会话保留。当用户明确说「我主要投XX」「坐标XX」「技能栈是XX」「工作X年」这类信息时调用。不要用它记录一次性投递事件。",
            "parameters": {"type": "object",
                "properties": {
                    "facts": {"type": "array", "description": "要记住的偏好条目",
                        "items": {"type": "object",
                            "properties": {
                                "key": {"type": "string", "description": "字段名，如 目标方向/所在城市/技能栈/工作经验/求职阶段"},
                                "value": {"type": "string", "description": "内容，如 前端/杭州/Vue、React/3年社招"},
                            },
                            "required": ["key", "value"]}},
                },
                "required": ["facts"]},
        }},
    },
    "recall_memory": {
        "function": _recall_memory,
        "schema": {"type": "function", "function": {
            "name": "recall_memory",
            "description": "取回该用户的长期偏好画像（目标方向/所在城市/技能栈等），在需要结合用户背景回答问题、给建议时先调用",
            "parameters": {"type": "object", "properties": {}, "required": []},
        }},
    },
}

TOOL_SCHEMAS = [entry["schema"] for entry in TOOLS.values()]


def _make_executor(ctx: dict):
    """构造给 chat_with_tools 用的工具执行器：name+args → 执行 → 结构化结果。

    约定返回：成功 {"ok": True, "result": <工具返回 dict>}
             失败 {"ok": False, "error": "..."}（未知工具 / 异常）
    工具内部的业务错误（如缺参数提示）会作为 result 返回，LLM 据此追问用户。
    """
    def executor(name: str, args: dict) -> dict:
        entry = TOOLS.get(name)
        if not entry:
            return {"ok": False, "error": f"未知工具 {name}"}
        try:
            result = entry["function"](ctx, **args)
            return {"ok": True, "result": result}
        except Exception as e:
            return {"ok": False, "error": f"{name} 执行失败: {e}"}
    return executor


# ── 格式化层（把结构化 dict 还原成文案，供降级路径 / 调试用） ──

def _format_result(intent: str, data: dict) -> str:
    """把工具返回的结构化 dict 格式化成人类可读文案（与旧版行为一致）。"""
    if intent == "query_today_count":
        items = data.get("items") or []
        if not items:
            return "今天还没有投递记录 📭"
        header = f"📋 今天投了 {len(items)} 份："
        return header + "\n" + "\n".join(f"  {i+1}. {it['label']}" for i, it in enumerate(items))

    if intent == "query_date_count":
        if not data.get("ok"):
            return data.get("error", "查询失败")
        items = data.get("items") or []
        if not items:
            return f"📭 {data['date']}没有投递记录"
        header = f"📋 {data['date']}投了 {len(items)} 份："
        return header + "\n" + "\n".join(f"  {i+1}. {it['label']}" for i, it in enumerate(items))

    if intent == "query_pending":
        items = data.get("items") or []
        if not items:
            return "目前没有待跟进的投递 ✅"
        lines = [f"⏳ 待跟进（{len(items)} 家）："]
        for i, it in enumerate(items, 1):
            days_str = f"（{it.get('days')} 天）" if it.get("days") else ""
            lines.append(f"  {i}. {it['company']} - {it['position']}{days_str}")
        return "\n".join(lines)

    if intent == "query_interviews":
        interviews = data.get("interviews") or []
        no_date = data.get("no_date") or []
        if not interviews and not no_date:
            return "目前没有面试安排 📅"
        lines = ["📅 面试安排："]
        for it in interviews:
            lines.append(f"  • {it['label']} @ {it['date']}")
        if no_date:
            lines.append("")
            lines.append("⏳ 以下岗位已进入面试阶段，待补充面试时间：")
            for label in no_date:
                lines.append(f"  • {label}")
        return "\n".join(lines)

    if intent == "query_statistics":
        if not data.get("ok"):
            return data.get("error", "查询失败")
        if data.get("empty"):
            return "表格为空，还没有投递记录"
        return (f"📊 投递统计\n总投递：{data['total']}\n待投递：{data['to_apply']}\n"
                f"面试：{data['interview']}（{data['interview_rate']}%）\n待跟进：{data['pending']}\n"
                f"已跟进：{data['followed']}\n已失效：{data['lost']}")

    if intent == "query_record":
        if not data.get("ok"):
            return data.get("error", "查询失败")
        matches = data.get("matches") or []
        if not matches:
            return f"没找到「{data.get('company')}」的投递记录，试试用「投了{data.get('company')}xx岗位」新建一条？"
        lines = [f"📋 **{data.get('company')}** 的投递记录："]
        for i, it in enumerate(matches, 1):
            lines.append(f"\n  {i}. {it.get('position') or '未知岗位'}")
            lines.append(f"     结果：{it.get('result') or '未更新'}")
            lines.append(f"     状态：{it.get('status') or '未更新'}")
            if it.get("days"):
                lines.append(f"     投递 {it['days']} 天")
            if it.get("interview_date"):
                lines.append(f"     面试时间：{it['interview_date']}")
        return "\n".join(lines)

    if intent == "record_interview":
        return data.get("message") if data.get("ok") else data.get("error", "操作失败")

    if intent == "create_record":
        if not data.get("ok"):
            if data.get("duplicate"):
                return (f"⚠️ 表格中已有「{data['company']} - {data['position']}」的记录"
                        f"（状态：{data.get('existing_status') or '未更新'}）\n"
                        f"如果想更新状态，试试说「{data['company']}改成面试」\n"
                        f"如果想查进度，试试说「{data['company']}怎么样了」\n"
                        f"如果确实是重复投递，请补充具体说明后重试")
            return data.get("error", "创建失败")
        parts = ["✅ 已记录"]
        if data.get("company"):
            parts.append(data["company"])
        if data.get("position"):
            parts.append(data["position"])
        if data.get("platform"):
            parts.append(f"（{data['platform']}）")
        if data.get("jd_saved"):
            parts.append("📄 已保存 JD")
        msg = " ".join(parts)
        missing = data.get("missing") or []
        if missing:
            msg += f"\n📌 缺少{'、'.join(missing)}，可以直接发给我补充"
        elif not data.get("jd_saved"):
            msg += "\n📌 没识别到 JD 描述，需要补充的话直接发给我就行"
        else:
            msg += "\n需要补充什么直接告诉我就好"
        return msg

    if intent == "update_status":
        return data.get("message") if data.get("ok") else data.get("error", "操作失败")

    if intent == "trigger_follow_up":
        if not data.get("ok"):
            return data.get("error", "操作失败")
        if data.get("count", 0) == 0:
            return "目前没有需要跟进的投递 ✅"
        return f"📨 已推送 {data.get('sent')}/{data.get('count')} 条跟进提醒卡片"

    return "✅ 已完成"


# ── Helpers ──────────────────────────────────────────


def _parse_ts_ms(ts, tz=timezone.utc):
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
        # Pure numeric string (ms or s timestamp)
        if ts.isdigit():
            val = int(ts)
            if 1_000_000_000 <= val < 100_000_000_000:
                val = val * 1000
            return val
        # Date string "YYYY-MM-DD" or "YYYY-MM-DD HH:MM"
        try:
            dt = datetime.strptime(ts[:10], "%Y-%m-%d")
            return int(dt.replace(tzinfo=tz).timestamp() * 1000)
        except (ValueError, IndexError):
            pass
    return None


def _reply(client: FeishuClient, to: str, text: str, id_type: str):
    """Send reply, split long messages if needed."""
    if not text:
        text = "✅ 已完成"
    if len(text) <= 1500:
        client.send_text(to, text, id_type)
        return
    # Split into chunks at newline boundaries
    chunks = []
    for line in text.split("\n"):
        candidate = "\n".join(chunks + [line])
        if len(candidate) > 1500:
            client.send_text(to, "\n".join(chunks), id_type)
            chunks = [line]
        else:
            chunks.append(line)
    if chunks:
        client.send_text(to, "\n".join(chunks), id_type)


def _get_days(record: dict, client: FeishuClient) -> int:
    """Calculate days since application."""
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
    return 999


# ── 主流程 ──────────────────────────────────────────


def _generate_reply(client: FeishuClient, sender_id: str, message_text: str,
                    today_str: str, receive_id_type: str) -> str:
    """核心 agent 逻辑：组装消息 → 走 tool-use 循环 → 返回自然语言回复。

    与发送解耦，便于本地测试。失败时降级到 _fallback_reply（旧 classify 路径）。
    """
    history = get_history(sender_id)
    messages = [{"role": "system", "content": AGENT_SYSTEM_PROMPT.format(today=today_str)}]
    messages.extend(history)
    messages.append({"role": "user", "content": message_text})

    ctx = {"client": client, "sender_id": sender_id, "receive_id_type": receive_id_type}
    executor = _make_executor(ctx)

    try:
        return LLMClient().chat_with_tools(messages, TOOL_SCHEMAS, executor)
    except Exception as e:
        return _fallback_reply(client, sender_id, message_text, today_str, receive_id_type, e)


def _fallback_reply(client: FeishuClient, sender_id: str, message_text: str,
                    today_str: str, receive_id_type: str, err) -> str:
    """降级路径：旧 classify + 硬编码分发（保证不支持 function calling 的端点也能用）。"""
    print(f"  ⚠️ chat_with_tools 失败，回退 classify 路径: {err}")
    try:
        result = LLMClient().classify(OLD_SYSTEM_PROMPT.format(today=today_str), message_text)
        intent = result.get("intent", "chat")
        params = result.get("params", {})
        ctx = {"client": client, "sender_id": sender_id, "receive_id_type": receive_id_type}

        if intent == "query_today_count":
            data = _query_today_count(ctx)
        elif intent == "query_date_count":
            data = _query_date_count(ctx, date_ref=params.get("date_ref", ""))
        elif intent == "query_pending":
            data = _query_pending(ctx)
        elif intent == "query_interviews":
            data = _query_interviews(ctx)
        elif intent == "query_statistics":
            data = _query_statistics(ctx)
        elif intent == "query_record":
            data = _query_record(ctx, company=params.get("company", ""), position=params.get("position", ""))
        elif intent == "record_interview":
            data = _record_interview(ctx, company=params.get("company", ""),
                                     interview_time=params.get("interview_time", ""),
                                     position=params.get("position", ""))
        elif intent == "create_record":
            data = _execute_create(ctx, company=params.get("company", ""), position=params.get("position", ""),
                                   platform=params.get("platform", ""), jd=params.get("jd", ""))
        elif intent == "update_status":
            data = _execute_update(ctx, company=params.get("company", ""), new_status=params.get("new_status", ""))
        elif intent == "trigger_follow_up":
            data = _trigger_follow_up(ctx)
        else:
            return HELP_TEXT

        return _format_result(intent, data)
    except Exception as e:
        return f"🤖 处理出错：{e}"


def handle_message(sender_id: str, message_text: str,
                   receive_id_type: str = "open_id"):
    """处理一条用户私聊消息并发送回复（入口签名保持不变）。"""
    client = FeishuClient()
    today_str = datetime.now().strftime("%Y-%m-%d")

    try:
        reply_text = _generate_reply(client, sender_id, message_text, today_str, receive_id_type)
    except Exception as e:
        reply_text = f"🤖 处理出错：{e}"

    # 记录本轮对话到短期记忆（有内容才存）
    append_turn(sender_id, message_text, reply_text)
    _reply(client, sender_id, reply_text, receive_id_type)
