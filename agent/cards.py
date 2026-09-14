"""飞书消息卡片模板"""

from status_rules import card_actions_for


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
