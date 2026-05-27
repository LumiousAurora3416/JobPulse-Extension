"""飞书消息卡片模板"""

from config import FEISHU_APP_TOKEN, FEISHU_TABLE_ID


def follow_up_card(company: str, position: str, days: int, url: str, record_id: str, callback_base: str = ""):
    """
    投递跟进提醒卡片
    callback_base 不为空时使用交互按钮（需部署回调服务）
    为空时使用链接按钮（直接打开表格）
    """
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
            {"tag": "action", "actions": _build_actions(company, position, record_id, callback_base)},
        ],
    }
    return card


def _build_actions(company: str, position: str, record_id: str, callback_base: str):
    if callback_base:
        # 交互按钮（需回调服务接收飞书 card action 回调）
        return [
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "✏️ 修改为面试"},
                "type": "primary",
                "value": {"action": "update_status", "record_id": record_id, "status": "面试"},
                "confirm": {"title": {"tag": "plain_text", "content": "确认修改为面试？"}, "text": {"tag": "plain_text", "content": f"将 {company} - {position} 的状态更新为「面试」"}},
            },
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "❌ 修改为被拒/无反馈"},
                "type": "danger",
                "value": {"action": "update_status", "record_id": record_id, "status": "被拒/无反馈"},
                "confirm": {"title": {"tag": "plain_text", "content": "确认无反馈？"}, "text": {"tag": "plain_text", "content": f"将 {company} - {position} 的状态更新为「被拒/无反馈」"}},
            },
        ]
    else:
        # 链接按钮：点开飞书表格手动编辑
        table_url = f"https://bytedance.feishu.cn/base/{FEISHU_APP_TOKEN}?table={FEISHU_TABLE_ID}"
        return [
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "✏️ 打开表格更新"},
                "type": "primary",
                "url": table_url,
            },
        ]


def analysis_card(summary: str, insights: list[str], chart_url: str = ""):
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
