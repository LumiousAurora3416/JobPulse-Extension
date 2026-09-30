"""飞书消息卡片模板"""

from datetime import datetime, timezone, timedelta

from status_rules import card_actions_for

CST = timezone(timedelta(hours=8))
DAY_MS = 86400000


def _result_icon(result: str) -> str:
    """给结果配个图标：offer 庆祝、面试绿、各种挂红、其余中性。"""
    if result == "offer":
        return "🎉"
    if result == "面试":
        return "✅"
    if result and result.endswith("挂"):
        return "❌"
    if result == "放弃":
        return "🚪"
    if result == "无反馈":
        return "📋"
    return "🔹"


def _action_button(company: str, position: str, record_id: str, label: str, value: str, index: int):
    """构造一颗回调按钮。写入的 value 恒取自 status_rules 定义的结果值。"""
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": label},
        "type": "primary" if index == 0 else ("danger" if value.endswith("挂") else "default"),
        "value": {"action": "update_status", "record_id": record_id, "status": value},
        "confirm": {
            "title": {"tag": "plain_text", "content": f"确认更新为「{value}」？"},
            "text": {"tag": "plain_text", "content": f"将 {company} - {position} 更新为「{value}」"},
        },
    }


def follow_up_card(company: str, position: str, days: int, url: str, record_id: str, result: str = ""):
    """投递跟进提醒卡片（交互按钮，回调地址在飞书应用级别配置）

    按钮按**当前结果**动态生成（status_rules.CARD_ACTIONS）：每颗按钮写入的值必然
    是结果列的合法选项，从结构上杜绝「按钮写了个不存在的选项 → 整条更新失败」。
    """
    elements = [
        {
            "tag": "div",
            "fields": [
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**公司**\n{company}"}},
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**岗位**\n{position}"}},
            ],
        },
        {"tag": "hr"},
        {
            "tag": "div",
            "fields": [
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**已投递**\n{days} 天"}},
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**当前进展**\n{_result_icon(result)} {result or '—'}"}},
            ],
        },
    ]
    if url:
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"[🔗 去官网跟进]({url})"}})

    actions = [
        _action_button(company, position, record_id, label, value, idx)
        for idx, (label, value) in enumerate(card_actions_for(result))
    ]
    if actions:
        elements.append({"tag": "hr"})
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "请更新该投递的进展："}})
        elements.append({"tag": "action", "actions": actions})

    return {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": "📌 投递跟进提醒"}, "template": "blue"},
        "elements": elements,
    }


def updated_card(company: str, position: str, new_status: str):
    """按钮点击后返回的「已更新」卡片，替换原卡片"""
    icon = _result_icon(new_status)
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"{icon} 进展已更新"},
            "template": "green",
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**公司**：{company}\n**岗位**：{position}\n**进展**：{icon} {new_status}"}},
            {"tag": "hr"},
            {"tag": "div", "text": {"tag": "lark_md", "content": "📌 表格已自动更新，无需额外操作"}},
        ],
    }
    return card


def analysis_card(summary: str, insights: list[str]):
    """周度投递归因分析卡片"""
    elements = [
        {"tag": "div", "text": {"tag": "lark_md", "content": summary}},
        {"tag": "hr"},
    ]
    for tip in insights:
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"• {tip}"}})

    card = {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": "📊 投递复盘周报"}, "template": "purple"},
        "elements": elements,
    }
    return card


def stats_card(total: int, to_apply: int, in_progress: int, offered: int, lost: int, quiet: int):
    """投递数据统计卡片（按「结果」状态机统计）

    in_progress = 简历+测评+面试（还在流程里）
    offered     = offer
    lost        = 各轮挂（简历挂/一面挂/二面挂/三面挂）
    quiet       = 无反馈 + 放弃
    """
    offered_rate = round(offered / total * 100, 1) if total else 0
    progress_rate = round(in_progress / total * 100, 1) if total else 0
    lost_rate = round(lost / total * 100, 1) if total else 0

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "📈 投递数据统计"},
            "template": "blue",
        },
        "elements": [
            {
                "tag": "div",
                "fields": [
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"**总投递数**\n{total}"}},
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"**待投递**\n{to_apply}"}},
                ],
            },
            {
                "tag": "div",
                "fields": [
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"**进行中**\n{in_progress} ({progress_rate}%)"}},
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"**offer**\n{offered} ({offered_rate}%)"}},
                ],
            },
            {
                "tag": "div",
                "fields": [
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"**已挂**\n{lost} ({lost_rate}%)"}},
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"**无反馈/放弃**\n{quiet}"}},
                ],
            },
            {"tag": "hr"},
            {"tag": "div", "text": {"tag": "lark_md", "content": f"offer 转化率：{offered_rate}%"}},
        ],
    }
    return card


def interview_reminder_card(company: str, position: str, interview_date: str, location: str = ""):
    """面试日程提醒卡片"""
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "⏰ 面试提醒"},
            "template": "orange",
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**公司**：{company}\n**岗位**：{position}\n**时间**：{interview_date}" + (f"\n**地点**：{location}" if location else "")}},
            {"tag": "hr"},
            {"tag": "div", "text": {"tag": "lark_md", "content": "祝面试顺利！"}},
        ],
    }
    return card


# ── 待办清单（邮件监控写入的「待办」表） ──────────────────────

TODO_TYPE_ICONS = {
    "测评": "📝",
    "笔试": "✍️",
    "面试": "🎤",
    "完善资料": "📄",
    "其他": "🔹",
    "提醒": "🔔",
}

TODO_BUTTON_LABELS = {
    "测评": "🚀 去做测评",
    "笔试": "🚀 去做笔试",
    "面试": "🎤 参加面试",
    "完善资料": "📄 去填写",
    "其他": "🔗 打开",
    "提醒": "🔔 查看提醒",
}

MAX_TODO_ITEMS = 10   # 卡片单次最多展开几条，超出只显示计数（避免卡片过长）


def _fmt_ms(ms: int, fmt: str) -> str:
    return datetime.fromtimestamp(ms / 1000, CST).strftime(fmt)


def _todo_when(deadline_ms, now_ms: int) -> str:
    """把截止时间说成人话：过期 / 今天 / 还有几天"""
    if not deadline_ms:
        return "无截止时间"
    if deadline_ms < now_ms:
        return f"⚠️ 已过期 {int((now_ms - deadline_ms) / DAY_MS) + 1} 天"
    if deadline_ms - now_ms < DAY_MS:
        return f"⏰ 今天 {_fmt_ms(deadline_ms, '%H:%M')} 截止"
    return f"⏳ 还有 {int((deadline_ms - now_ms) / DAY_MS)} 天（{_fmt_ms(deadline_ms, '%m-%d %H:%M')}）"


def _merge_todos(todos: list[dict]) -> list[dict]:
    """按「公司+岗位+事项」聚合。

    招聘系统常为同一件事发「邀请」+「提醒」多封邮件，数据层是全量落表的
    （宁可多落不漏），展示层在这里合并，只留截止最早的那条。

    key 里**不放「类型」**：第二封的类型是「提醒」，放进去就归并不了了。
    改用「事项」——同一件事的两封邮件事项相同（mail_watch 的 prompt 要求
    提醒邮件的 summary 与原条目一致），不同的事事项不同。
    """
    best: dict[tuple, dict] = {}
    for t in todos:
        key = (t.get("company") or "", t.get("position") or "", t.get("summary") or "")
        cur = best.get(key)
        if cur is None:
            best[key] = dict(t, merged=1)
            continue
        cur["merged"] += 1
        # 类型要保住"本体"：第二封是「提醒」，别把原类型顶掉
        if cur.get("type") == "提醒" and t.get("type") != "提醒":
            cur["type"] = t["type"]
        # 取更早的截止时间；原本没截止的，被有截止的取代
        if t.get("deadline") and (not cur.get("deadline") or t["deadline"] < cur["deadline"]):
            cur["deadline"] = t["deadline"]
        if not cur.get("url") and t.get("url"):
            cur["url"] = t["url"]
    return list(best.values())


def todo_list_card(todos: list[dict]):
    """待办清单卡片

    todos 每条：company / position / type / summary / deadline(毫秒|None) / url

    排序：未过期按截止时间升序（无截止的排最后）；已过期的单独收在底部一行，
    不占版面但也不丢——「超期未完成」恰恰是最需要你知道的那一类。
    """
    now_ms = int(datetime.now(CST).timestamp() * 1000)
    items = _merge_todos(todos)

    active = [t for t in items if not t.get("deadline") or t["deadline"] >= now_ms]
    expired = [t for t in items if t.get("deadline") and t["deadline"] < now_ms]
    active.sort(key=lambda t: t["deadline"] if t.get("deadline") else float("inf"))

    elements = []
    if not active:
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": "🎉 没有待办的测评/笔试/面试，轻松一下"},
        })

    for t in active[:MAX_TODO_ITEMS]:
        icon = TODO_TYPE_ICONS.get(t.get("type"), "🔹")
        title = f"{icon} **{t.get('company') or '未知公司'}**"
        if t.get("position"):
            title += f" · {t['position']}"
        lines = [title, f"{t.get('type') or '待办'}　{_todo_when(t.get('deadline'), now_ms)}"]
        if t.get("summary"):
            lines.append(t["summary"][:140])
        if t.get("merged", 1) > 1:
            lines.append(f"> 另有 {t['merged'] - 1} 封相关邮件")
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}})
        if t.get("url"):
            elements.append({"tag": "action", "actions": [{
                "tag": "button",
                "text": {"tag": "plain_text",
                         "content": TODO_BUTTON_LABELS.get(t.get("type"), "🔗 打开")},
                "type": "primary",
                "url": t["url"],
            }]})
        elements.append({"tag": "hr"})

    if len(active) > MAX_TODO_ITEMS:
        elements.append({"tag": "div", "text": {"tag": "lark_md",
            "content": f"…还有 **{len(active) - MAX_TODO_ITEMS}** 条待办，去多维表格查看全部"}})

    if expired:
        elements.append({"tag": "div", "text": {"tag": "lark_md",
            "content": f"📁 另有 **{len(expired)}** 条已过期未勾选（可能已错过，去表里确认下）"}})

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"📋 待办清单（{len(active)}）"},
            "template": "orange" if active else "green",
        },
        "elements": elements,
    }


def rejection_insight_card(company: str, position: str, insights: list[str]):
    """拒信归因洞察卡片"""
    elements = [
        {"tag": "div", "text": {"tag": "lark_md", "content": f"**公司**：{company}　|　**岗位**：{position}"}},
        {"tag": "hr"},
    ]
    for tip in insights:
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"• {tip}"}})

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "🔍 拒信归因分析"},
            "template": "red",
        },
        "elements": elements,
    }
    return card
