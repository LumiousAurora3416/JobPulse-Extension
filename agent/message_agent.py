"""
JobPulse Message Agent — 处理用户私聊消息
流程: LLM 意图识别 → Tool 执行 → 回复
"""

import json
import time
from datetime import datetime, timezone, timedelta

from feishu import FeishuClient
from llm_client import LLMClient
from cards import follow_up_card
from config import FOLLOW_UP_HOURS


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
- query_record: Asking about a specific company's application status (already in the table)
  Examples: "我投的字节怎么样了" "腾讯那个岗位有消息吗" "阿里云现在什么情况" "查一下我投的公司进度"
  Extract: company (公司名, required), position (岗位名, optional)
- record_interview: Recording or updating interview time for an application
  Examples: "字节周三下午两点面试" "腾讯后天上午十点面试" "帮我记下面试时间" "阿里云面试改到周五了"
  Extract: company (公司名, required), interview_time (面试时间, required, use YYYY-MM-DD HH:MM format in UTC+8), position (岗位名, optional)
- create_record: Logging a new application the user just submitted
  Examples: "投了字节前端" "刚在Boss投了快手" "记一下我投了腾讯"
  DO NOT classify as create_record if the user is asking about an existing record. Use query_record instead.
  Extract: company (公司名), position (岗位名), platform (平台名, optional)
- update_status: Changing an application's follow-up status
  Examples: "腾讯有反馈了" "改成面试" "字节挂了" "美团有消息了"
  Extract: company (公司名), new_status (面试/无反馈/简历挂/已跟进)
- trigger_follow_up: Manually push follow-up reminder cards for all pending applications
  Examples: "推送卡片" "发送提醒" "推送跟进" "发跟进卡片" "推送"
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
        elif intent == "query_record":
            data = _query_record(client, params)
        elif intent == "record_interview":
            data = _record_interview(client, params)
        elif intent == "create_record":
            data = _execute_create(client, params)
        elif intent == "update_status":
            data = _execute_update(client, params)
        elif intent == "trigger_follow_up":
            data = _trigger_follow_up(client, sender_id, receive_id_type)
        else:
            data = (
                "你好！我可以帮你：\n"
                "📋 查询今天投递：「今天投了多少」\n"
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
    """Query upcoming / ongoing interviews.
    Include records with 结果=面试 even if 面试时间 is not set yet."""
    records = client.list_records()
    interviews = []
    no_date = []
    for rec in records:
        result = client.field_value(rec, "结果")
        interview_date = client.field_value(rec, "面试时间")
        if result != "面试" and not interview_date:
            continue
        company = client.field_value(rec, "公司")
        position = client.field_value(rec, "岗位")
        label = f"{company or '未知'} - {position or '未知'}"
        if interview_date:
            interviews.append((label, str(interview_date)))
        else:
            no_date.append(label)

    if not interviews and not no_date:
        return "目前没有面试安排 📅"

    lines = ["📅 面试安排："]
    for label, d in interviews:
        lines.append(f"  • {label} @ {d}")
    if no_date:
        lines.append("")
        lines.append(f"⏳ 以下岗位已进入面试阶段，待补充面试时间：")
        for label in no_date:
            lines.append(f"  • {label}")
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


def _query_record(client: FeishuClient, params: dict) -> str:
    """Query a specific company's application record."""
    company = params.get("company", "")
    if not company:
        return "你想查哪家公司的投递情况？说清楚公司名就行"

    records = client.list_records()
    matches = []
    for rec in records:
        c = client.field_value(rec, "公司")
        # Try exact match first, then partial
        if c == company or (company in c or c in company):
            position = client.field_value(rec, "岗位")
            result = client.field_value(rec, "结果")
            status = client.field_value(rec, "提醒状态")
            days = client.field_value(rec, "投递天数")
            interview_date = client.field_value(rec, "面试时间")
            matches.append((c, position, result, status, days, interview_date))

    if not matches:
        return f"没找到「{company}」的投递记录，试试用「投了{company}xx岗位」新建一条？"

    lines = [f"📋 **{company}** 的投递记录："]
    for i, (c, p, r, s, d, iv) in enumerate(matches, 1):
        lines.append(f"\n  {i}. {p or '未知岗位'}")
        lines.append(f"     结果：{r or '未更新'}")
        lines.append(f"     状态：{s or '未更新'}")
        if d:
            lines.append(f"     投递 {d} 天")
        if iv:
            lines.append(f"     面试时间：{iv}")
    return "\n".join(lines)


def _record_interview(client: FeishuClient, params: dict) -> str:
    """Record or update interview time for an application."""
    company = params.get("company", "")
    interview_time = params.get("interview_time", "")
    position = params.get("position", "")

    if not company:
        return "你说的是哪家公司？比如「字节周三下午两点面试」"
    if not interview_time:
        return "面试时间是什么时候？比如「字节周三下午两点面试」"

    # Parse YYYY-MM-DD HH:MM to millisecond timestamp (UTC+8)
    tz8 = timezone(timedelta(hours=8))
    try:
        dt = datetime.strptime(interview_time, "%Y-%m-%d %H:%M")
        dt = dt.replace(tzinfo=tz8)
        time_ms = int(dt.timestamp() * 1000)
    except ValueError:
        return f"时间「{interview_time}」我没看懂，直接跟我说「字节周三下午两点面试」就好"

    # Find matching record
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
        return f"没找到「{company}」的投递记录"

    record_id = target.get("record_id", "")
    fields = {"面试时间": time_ms, "结果": "面试", "提醒状态": "有反馈"}
    ok = client.update_record(record_id, fields)
    if not ok:
        return "❌ 更新失败，请稍后重试"

    time_str = dt.strftime("%Y年%m月%d日 %H:%M")
    pos_str = f"（{target_position}）" if target_position else ""
    return f"✅ 已记录 {company}{pos_str} 面试时间：{time_str}"


def _execute_create(client: FeishuClient, params: dict) -> str:
    """Create a new application record."""
    company = params.get("company", "")
    position = params.get("position", "")
    platform = params.get("platform", "")

    if not company and not position:
        return "没识别到公司和岗位信息，麻烦说清楚一些，比如「我在Boss投了字节前端」"

    # Duplicate check: if exact same company+position already exists, warn
    if company and position:
        records = client.list_records()
        for rec in records:
            existing_company = client.field_value(rec, "公司")
            existing_position = client.field_value(rec, "岗位")
            if existing_company == company and existing_position == position:
                existing_status = client.field_value(rec, "结果")
                return (
                    f"⚠️ 表格中已有「{company} - {position}」的记录"
                    f"（状态：{existing_status or '未更新'}）\n"
                    f"如果想更新状态，试试说「{company}改成面试」\n"
                    f"如果想查进度，试试说「{company}怎么样了」\n"
                    f"如果确实是重复投递，请补充具体说明后重试"
                )

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


def _get_days(record: dict, client: FeishuClient) -> int:
    """Calculate days since application."""
    formula_val = client.field_value(record, "投递天数")
    if formula_val and formula_val.replace(".", "").isdigit():
        return int(float(formula_val))
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
    return 999


def _trigger_follow_up(client: FeishuClient, sender_id: str,
                       receive_id_type: str) -> str:
    """Push follow-up reminder cards for all pending applications."""
    records = client.list_records()
    threshold_days = FOLLOW_UP_HOURS / 24

    pending = []
    for rec in records:
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
        return "目前没有需要跟进的投递 ✅"

    sent = 0
    for company, position, days, url, record_id in pending:
        card = follow_up_card(company, position, days, url, record_id)
        msg_id = client.send_card(sender_id, card, receive_id_type)
        if msg_id:
            client.update_record(record_id, {"消息ID": msg_id})
            sent += 1
        time.sleep(0.3)

    return f"📨 已推送 {sent}/{len(pending)} 条跟进提醒卡片"
