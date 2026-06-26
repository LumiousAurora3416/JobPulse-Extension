"""
飞书卡片交互回调服务（Flask 版）

用法：
  python callback_server.py          # 启动服务
  ngrok http 8000                    # 暴露公网

飞书回调配置：
  开放平台 → 应用 → 消息卡片 → 回调地址: {公网URL}/callback
"""

import json
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from feishu import FeishuClient
from cards import updated_card

try:
    from flask import Flask, request, Response
except ImportError:
    print("⚠️ 请先安装 Flask: pip install flask")
    sys.exit(1)

app = Flask(__name__)


def json_resp(data: dict, status=200):
    """手动构建 JSON 响应"""
    body = json.dumps(data, ensure_ascii=False)
    resp = Response(body, status=status)
    resp.headers["Content-Type"] = "application/json; charset=utf-8"
    resp.headers["Content-Length"] = str(len(body.encode("utf-8")))
    return resp


@app.route("/callback", methods=["POST"])
def callback():
    payload = request.get_json(force=True, silent=True) or {}

    # 1. 飞书 URL 挑战验证（Event Subscription 配置时触发）
    if "challenge" in payload:
        return json_resp({"challenge": payload["challenge"]})

    # 2. 事件订阅（消息事件等）
    if "header" in payload:
        handle_event(payload)
        # Event subscription expects a quick 200 with code:0
        return json_resp({"code": 0})

    # 3. 卡片按钮回调
    result = handle_card_action(payload)
    return json_resp(result)


@app.route("/health")
def health():
    return json_resp({"status": "ok"})


@app.route("/")
def index():
    return json_resp({"service": "JobPulse Callback", "status": "running"})


def handle_card_action(payload: dict) -> dict:
    """处理卡片按钮回调"""
    action = payload.get("action", payload)
    value = action.get("value", {})
    action_type = value.get("action")
    record_id = value.get("record_id")
    new_status = value.get("status")

    print(f"  📩 收到回调: action={action_type}, record_id={record_id}, status={new_status}")
    # 打印关键字段，排查 message_id 是否存在
    print(f"  🔍 payload 字段: message_id={'有' if payload.get('message_id') else '无'}, open_id={'有' if payload.get('open_id') else '无'}, card={'有' if payload.get('card') else '无'}")

    if action_type != "update_status" or not record_id:
        return {"code": 400, "msg": "无效的回调参数"}

    # 更新飞书表格
    client = FeishuClient()
    status_map = {
        "面试": {"提醒状态": "有反馈", "结果": "面试"},
        "无反馈": {"提醒状态": "已跟进", "结果": "无反馈"},
        "简历挂": {"提醒状态": "已失效", "结果": "简历挂"},
    }
    fields = status_map.get(new_status, {"提醒状态": "已跟进"})

    ok = client.update_record(record_id, fields)
    if not ok:
        print(f"  ❌ 更新记录失败")
        return {"code": 500, "msg": "更新失败"}

    print(f"  ✅ 已更新记录 {record_id} → {new_status}")

    # 获取记录详情，优先从飞书表格"消息ID"字段读取 message_id
    rec = client.get_record(record_id)
    company = client.field_value(rec, "公司") if rec else ""
    position = client.field_value(rec, "岗位") if rec else ""
    message_id = client.field_value(rec, "消息ID") if rec else ""

    # fallback: 本地 message_store.json
    if not message_id:
        store_path = os.path.join(os.path.dirname(__file__), "message_store.json")
        if os.path.exists(store_path):
            try:
                msg_store = json.load(open(store_path))
                message_id = msg_store.get(record_id, "")
            except (json.JSONDecodeError, OSError):
                pass

    if message_id:
        new_card = updated_card(company, position, new_status)
        print(f"  🔄 更新卡片 message_id={message_id[:20]}...")
        card_ok = client.update_message_card(message_id, new_card)
        print(f"  {'✅' if card_ok else '❌'} 卡片更新: {'成功' if card_ok else '失败'}")
    else:
        print(f"  ⚠️ 未找到 message_id，无法更新卡片")

    return {"code": 0}


def handle_event(payload: dict):
    """Handle Feishu event subscription events."""
    header = payload.get("header", {})
    event_type = header.get("event_type", "")
    print(f"  📩 收到事件: {event_type}")

    if event_type == "im.message.receive_v1":
        handle_message_event(payload.get("event", {}))


def handle_message_event(event: dict):
    """Handle incoming user message event (im.message.receive_v1)."""
    sender = event.get("sender", {})
    message = event.get("message", {})

    chat_type = message.get("chat_type", "")
    message_type = message.get("message_type", "")

    # Only handle private chat text messages
    # Feishu v2 event uses "p2p", some older versions use "private"
    if chat_type not in ("private", "p2p") or message_type != "text":
        return

    sender_id_obj = sender.get("sender_id", {})
    open_id = sender_id_obj.get("open_id", "")
    if not open_id:
        return

    content_str = message.get("content", "{}")
    try:
        content = json.loads(content_str)
        text = content.get("text", "").strip()
    except (json.JSONDecodeError, TypeError):
        return

    if not text:
        return

    print(f"  💬 用户消息 from {open_id}: {text}")

    # Process in background thread so webhook returns immediately
    thread = threading.Thread(
        target=handle_bot_message,
        args=(open_id, text),
        daemon=True,
    )
    thread.start()


def handle_bot_message(open_id: str, text: str):
    """Route user message to message_agent for processing."""
    try:
        # Check LLM API key before proceeding
        import os
        print(f"  🔍 DEBUG: LLM_API_KEY env = '{os.environ.get('LLM_API_KEY', '<NOT SET>')}'")
        print(f"  🔍 DEBUG: LLM_API_KEY type = {type(os.environ.get('LLM_API_KEY', ''))}")
        from config import LLM_API_KEY
        print(f"  🔍 DEBUG: config.LLM_API_KEY = '{LLM_API_KEY}' (len={len(LLM_API_KEY)})")
        if not LLM_API_KEY:
            client = FeishuClient()
            client.send_text(
                open_id,
                "🤖 管理员还未配置 LLM API Key，暂时无法处理消息",
            )
            return

        from message_agent import handle_message
        handle_message(open_id, text)

    except Exception as e:
        print(f"  ❌ 处理消息出错: {e}")
        import traceback
        traceback.print_exc()


def extract_card_field(payload: dict, field_name: str) -> str:
    """从回调 payload 的卡片结构中提取字段值"""
    card = payload.get("card", {})
    elements = card.get("elements", [])
    for el in elements:
        if el.get("tag") != "div":
            continue
        fields = el.get("fields", [])
        for f in fields:
            md = f.get("text", {}).get("content", "")
            if md.startswith(f"**{field_name}**"):
                return md.replace(f"**{field_name}**", "").strip()
    return ""


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"🚀 JobPulse 回调服务运行在 http://0.0.0.0:{port}/callback")
    print(f"   使用 ngrok 暴露公网: ngrok http {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
