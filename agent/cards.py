"""飞书消息卡片模板"""


def follow_up_card(company: str, position: str, days: int, url: str, record_id: str):
    """投递跟进提醒卡片（交互按钮，回调地址在飞书应用级别配置）"""
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "📌 投递跟进提醒"},
            "template": "blue",
        },
        "elements": [
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
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"**去官网跟进**\n[🔗 打开链接]({url})"} if url else {"tag": "plain_text", "content": " "}},
                ],
            },
            {"tag": "hr"},
            {"tag": "div", "text": {"tag": "lark_md", "content": "请更新该投递的进展状态："}},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "✏️ 面试"},
                        "type": "primary",
                        "value": {"action": "update_status", "record_id": record_id, "status": "面试"},
                        "confirm": {"title": {"tag": "plain_text", "content": "确认修改为面试？"}, "text": {"tag": "plain_text", "content": f"将 {company} - {position} 更新为「面试」"}},
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "📋 无反馈"},
                        "type": "default",
                        "value": {"action": "update_status", "record_id": record_id, "status": "无反馈"},
                        "confirm": {"title": {"tag": "plain_text", "content": "确认无反馈？"}, "text": {"tag": "plain_text", "content": f"标记 {company} - {position} 为「已跟进，暂无反馈」"}},
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "❌ 简历挂"},
                        "type": "danger",
                        "value": {"action": "update_status", "record_id": record_id, "status": "简历挂"},
                        "confirm": {"title": {"tag": "plain_text", "content": "确认简历挂？"}, "text": {"tag": "plain_text", "content": f"将 {company} - {position} 更新为「简历挂」"}},
                    },
                ],
            },
        ],
    }
    return card


def updated_card(company: str, position: str, new_status: str):
    """按钮点击后返回的「已更新」卡片，替换原卡片"""
    status_icon = {"面试": "✅", "无反馈": "📋", "简历挂": "❌"}
    icon = status_icon.get(new_status, "✅")
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"{icon} 状态已更新"},
            "template": "green",
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**公司**：{company}\n**岗位**：{position}\n**状态**：{icon} {new_status}"}},
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


def stats_card(total: int, interview: int, pending: int, followed: int, lost: int):
    """投递数据统计卡片"""
    interview_rate = round(interview / total * 100, 1) if total else 0
    pending_rate = round(pending / total * 100, 1) if total else 0
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
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"**面试**\n{interview} ({interview_rate}%)"}},
                ],
            },
            {
                "tag": "div",
                "fields": [
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"**待跟进**\n{pending} ({pending_rate}%)"}},
                    {"is_short": True, "text": {"tag": "lark_md", "content": f"**已失效**\n{lost} ({lost_rate}%)"}},
                ],
            },
            {"tag": "hr"},
            {"tag": "div", "text": {"tag": "lark_md", "content": f"已跟进：{followed} | 转化率：{interview_rate}%"}},
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
