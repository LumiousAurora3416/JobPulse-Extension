"""
飞书卡片交互回调服务 — 处理按钮点击事件（零依赖，仅 Python 标准库）

用法 1 — 本地运行（配合 ngrok 暴露公网地址）：
  python callback_server.py
  ngrok http 8000

用法 2 — 部署到任意云服务器：
  python callback_server.py --port 8080

用法 3 — 部署到 Vercel（需安装 vercel cli）：
  vercel --prod

飞书回调配置：
  开放平台 → 应用 → 事件与回调 → 消息卡片
  → 回调地址设置为 {公网URL}/callback
"""

import json
import os
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

# 添加父目录到路径，方便导入 feishu.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from feishu import FeishuClient
from cards import updated_card


class CallbackHandler(BaseHTTPRequestHandler):
    """处理飞书卡片按钮回调"""

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/callback":
            self._handle_callback()
        else:
            self._respond(404, {"code": 404, "msg": "not found"})

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self._respond(200, {"status": "ok"})
        elif path == "/":
            self._respond(200, {"service": "JobPulse Callback", "status": "running"})
        else:
            self._respond(404, {"code": 404, "msg": "not found"})

    def _handle_callback(self):
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len)
        payload = json.loads(body)

        # 飞书 URL 挑战验证
        if "challenge" in payload:
            return self._respond(200, {"challenge": payload["challenge"]})

        result = handle_card_action(payload)
        self._respond(200, result)

    def _respond(self, status: int, data: dict):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def log_message(self, format, *args):
        print(f"[{self.log_date_time_string()}] {args[0]} {args[1]} {args[2]}")


def handle_card_action(payload: dict) -> dict:
    """
    处理卡片按钮回调
    飞书回调格式: https://open.feishu.cn/document/uAjLw4CM/ukzMukzMukzM/feishu-cards/card-action
    """
    # 飞书回调的 action 可能在 payload.action 或 payload 顶层
    action = payload.get("action", payload)
    value = action.get("value", {})
    action_type = value.get("action")
    record_id = value.get("record_id")
    new_status = value.get("status")

    print(f"  📩 收到回调: action={action_type}, record_id={record_id}, status={new_status}")

    if action_type != "update_status" or not record_id:
        return {"code": 400, "msg": "无效的回调参数"}

    client = FeishuClient()

    # 根据点击的按钮，更新「提醒状态」和「结果」
    status_map = {
        "面试": {"提醒状态": "有反馈", "结果": "面试"},
        "无反馈": {"提醒状态": "已跟进", "结果": "无反馈"},
        "简历挂": {"提醒状态": "已失效", "结果": "简历挂"},
    }
    fields = status_map.get(new_status, {"提醒状态": "已跟进"})

    ok = client.update_record(record_id, fields)

    # 从原 payload 中提取卡片信息（公司、岗位名）
    company = ""
    position = ""
    card_info = payload.get("card", {})
    header = card_info.get("header", {})
    if header:
        content = header.get("title", {}).get("content", "")
    elements = card_info.get("elements", [])
    for el in elements:
        fields_data = el.get("fields", [])
        for f in fields_data:
            md = f.get("text", {}).get("content", "")
            if md.startswith("**公司**"):
                company = md.replace("**公司**", "").strip()
            if md.startswith("**岗位**"):
                position = md.replace("**岗位**", "").strip()

    if ok:
        print(f"  ✅ 已更新记录 {record_id} → {new_status}")
        return {
            "code": 0,
            "msg": "success",
            "card": {
                "type": "raw",
                "data": updated_card(company, position, new_status),
            },
        }
    else:
        print(f"  ❌ 更新记录失败")
        return {"code": 500, "msg": "更新失败"}


def run_server(host="0.0.0.0", port=8000):
    server = HTTPServer((host, port), CallbackHandler)
    print(f"🚀 JobPulse 回调服务运行在 http://{host}:{port}/callback")
    print(f"   GET  /health — 健康检查")
    print(f"   POST /callback — 飞书卡片回调")
    print()
    print(f"📌 使用 ngrok 暴露公网地址:")
    print(f"   ngrok http {port}")
    print()
    print(f"📌 然后在飞书开放平台配置回调地址:")
    print(f"   https://open.feishu.cn/app/YOUR_APP_ID")
    print(f"   事件与回调 → 消息卡片 → 回调地址: https://你的域名/callback")
    print()
    print(f"📌 同时更新 cards.py 中的 callback_base")
    print(f"   将 callback_server 模块中的 CALLBACK_BASE 改为你的公网地址")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 服务已关闭")
        server.server_close()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        if idx + 1 < len(sys.argv):
            port = int(sys.argv[idx + 1])
    run_server(port=port)
