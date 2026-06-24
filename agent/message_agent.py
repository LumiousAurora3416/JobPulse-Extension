"""
JobPulse Message Agent — 处理用户私聊消息
流程: LLM 意图识别 → Tool 执行 → 回复
"""

import json
from datetime import datetime, timezone, timedelta

from feishu import FeishuClient
from llm_client import LLMClient


# System prompt for intent classification
SYSTEM_PROMPT = """You are a job tracking assistant. The user tracks job applications in a Feishu Bitable.

Current date: {today}

Classify the user's message into ONE intent. Return ONLY valid JSON (no markdown).

Intents:
- query_today_count: Asking about today's submissions count or list
  Examples: "今天投了多少" "今天投了哪些" "今天投了啥"
- query_pending: Asking about applications with no response / pending follow-up
  Examples: "哪些没反馈" "待跟进" "哪些还没消息" "还没回应的"
- query_interviews: Asking about upcoming interviews
  Examples: "面试安排" "最近面试" "什么时候面试"
- query_statistics: Asking for aggregate application stats
  Examples: "统计数据" "投递情况" "一共投了多少" "有多少面试"
- create_record: Logging a new application the user just submitted
  Examples: "投了字节前端" "刚在Boss投了快手" "记一下我投了腾讯" "面了阿里"
  Extract: company (公司名), position (岗位名), platform (平台名, optional)
- update_status: Changing an application's follow-up status
  Examples: "腾讯有反馈了" "改成面试" "字节挂了" "美团有消息了"
  Extract: company (公司名), new_status (面试/无反馈/简历挂/已跟进)
- chat: Greeting, thanks, small talk, unclear, or anything else not covered above

Return format:
{{"intent": "intent_name", "params": {{...}}}}
"""


def handle_message(sender_id: str, message_text: str,
                   receive_id_type: str = "open_id"):
    """Process an incoming user message and send a reply via Feishu."""
    client = FeishuClient()
    llm = LLMClient()

    today_str = datetime.now().strftime("%Y-%m-%d")
    system_prompt = SYSTEM_PROMPT.format(today=today_str)

    # Step 1: LLM intent classification
    try:
        result = llm.classify(system_prompt, message_text)
    except Exception as e:
        _reply(client, sender_id, f"🤖 处理出错：{e}", receive_id_type)
        return

    intent = result.get("intent", "chat")
    params = result.get("params", {})

    # Step 2: Execute tool
    try:
        if intent == "query_today_count":
            data = _query_today_count(client)
        elif intent == "query_pending":
            data = _query_pending(client)
        elif intent == "query_interviews":
            data = _query_interviews(client)
        elif intent == "query_statistics":
            data = _query_statistics(client)
        elif intent == "create_record":
            data = _execute_create(client, params)
        elif intent == "update_status":
            data = _execute_update(client, params)
        else:
            data = (
                "你好！我可以帮你：\n"
                "📋 查询今天投递：「今天投了多少」\n"
                "⏳ 查看待跟进：「哪些没反馈」\n"
                "📅 面试安排：「最近面试」\n"
                "📊 投递统计：「统计数据」\n"
                "✏️ 记录新投递：「投了字节前端」\n"
                "🔄 更新状态：「腾讯有反馈了」\n\n"
                "试试看吧！"
            )
        _reply(client, sender_id, data, receive_id_type)

    except Exception as e:
        _reply(client, sender_id, f"❌ 操作失败：{e}", receive_id_type)


# ── Helpers ──────────────────────────────────────────


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


# ── Tools ────────────────────────────────────────────


def _query_today_count(client: FeishuClient) -> str:
    """Query today's submissions from bitable records."""
    records = client.list_records()

    # Today's time range in ms timestamp (UTC+8)
    tz8 = timezone(timedelta(hours=8))
    now = datetime.now(tz8)
    today_start = datetime(now.year, now.month, now.day, tzinfo=tz8)
    today_end = today_start + timedelta(days=1)
    start_ms = int(today_start.timestamp() * 1000)
    end_ms = int(today_end.timestamp() * 1000)

    today_items = []
    for rec in records:
        created = rec.get("created_at") or rec.get("created_time", 0)
        try:
            ct = int(created)
            if start_ms <= ct < end_ms:
                company = client.field_value(rec, "公司")
                position = client.field_value(rec, "岗位")
                label = f"{company} - {position}" if company else (position or "未命名")
                today_items.append(label)
        except (ValueError, TypeError):
            pass

    if not today_items:
        return "今天还没有投递记录 📭"

    header = f"📋 今天投了 {len(today_items)} 份："
    return header + "\n" + "\n".join(f"  {i+1}. {item}" for i, item in enumerate(today_items))


def _query_pending(client: FeishuClient) -> str:
    """Query applications pending follow-up."""
    records = client.list_records()
    pending = []
    for rec in records:
        status = client.field_value(rec, "提醒状态")
        if status == "待跟进":
            company = client.field_value(rec, "公司")
            position = client.field_value(rec, "岗位")
            days = client.field_value(rec, "投递天数")
            pending.append((company or "未知", position or "未知", days))

    if not pending:
        return "目前没有待跟进的投递 ✅"

    lines = [f"⏳ 待跟进（{len(pending)} 家）："]
    for i, (c, p, d) in enumerate(pending, 1):
        days_str = f"（{d} 天）" if d else ""
        lines.append(f"  {i}. {c} - {p}{days_str}")
    return "\n".join(lines)


def _query_interviews(client: FeishuClient) -> str:
    """Query upcoming interviews."""
    records = client.list_records()
    interviews = []
    for rec in records:
        interview_date = client.field_value(rec, "面试时间")
        if not interview_date:
            continue
        company = client.field_value(rec, "公司")
        position = client.field_value(rec, "岗位")
        interviews.append((company or "未知", position or "未知", str(interview_date)))

    if not interviews:
        return "目前没有面试安排 📅"

    lines = ["📅 面试安排："]
    for c, p, d in interviews:
        lines.append(f"  • {c} - {p} @ {d}")
    return "\n".join(lines)


def _query_statistics(client: FeishuClient) -> str:
    """Aggregate application statistics."""
    records = client.list_records()
    total = len(records)
    if total == 0:
        return "表格为空，还没有投递记录"

    interview = sum(1 for r in records if client.field_value(r, "结果") == "面试")
    pending = sum(1 for r in records if client.field_value(r, "提醒状态") == "待跟进")
    followed = sum(1 for r in records if client.field_value(r, "提醒状态") == "已跟进")
    lost = sum(1 for r in records if client.field_value(r, "提醒状态") in ("已失效", "被拒/无反馈"))

    rate = round(interview / total * 100, 1) if total else 0
    return (
        f"📊 投递统计\n"
        f"总投递：{total}\n"
        f"面试：{interview}（{rate}%）\n"
        f"待跟进：{pending}\n"
        f"已跟进：{followed}\n"
        f"已失效：{lost}"
    )


def _execute_create(client: FeishuClient, params: dict) -> str:
    """Create a new application record."""
    company = params.get("company", "")
    position = params.get("position", "")
    platform = params.get("platform", "")

    if not company and not position:
        return "没识别到公司和岗位信息，麻烦说清楚一些，比如「我在Boss投了字节前端」"

    # Build fields with sensible defaults
    today = datetime.now()
    today_ms = int(datetime(today.year, today.month, today.day).timestamp() * 1000)

    fields = {
        "公司": company,
        "岗位": position,
        "结果": "简历",
        "提醒状态": "待跟进",
        "投递时间": today_ms,
    }
    record_id = client.create_record(fields)
    if not record_id:
        return "❌ 创建失败，请稍后重试"

    parts = ["✅ 已记录"]
    if company:
        parts.append(company)
    if position:
        parts.append(position)
    if platform:
        parts.append(f"（{platform}）")

    msg = " ".join(parts)

    missing = []
    if not company:
        missing.append("公司名")
    if not position:
        missing.append("岗位名")
    if missing:
        msg += f"\n📌 缺少{'、'.join(missing)}，可以直接发给我补充"
    else:
        msg += "\n需要补充 JD 的话直接发给我"

    return msg


def _execute_update(client: FeishuClient, params: dict) -> str:
    """Update an application's status."""
    valid_statuses = ("面试", "无反馈", "简历挂", "已跟进")
    company = params.get("company", "")
    new_status = params.get("new_status", "")

    if not company:
        return "没识别到是哪家公司，请说清楚公司名"
    if new_status not in valid_statuses:
        return f"支持的状态：{'、'.join(valid_statuses)}。你说是哪一种？"

    # Find matching record
    records = client.list_records()
    target = None
    for rec in records:
        if client.field_value(rec, "公司") == company:
            target = rec
            break

    if not target:
        return f"没找到「{company}」的投递记录"

    record_id = target.get("record_id", "")
    if not record_id:
        return "❌ 无法获取记录 ID"

    fields = {"提醒状态": new_status}
    if new_status == "面试":
        fields["结果"] = "面试"

    ok = client.update_record(record_id, fields)
    if not ok:
        return "❌ 更新失败，请稍后重试"

    return f"✅ 已将「{company}」更新为「{new_status}」"
