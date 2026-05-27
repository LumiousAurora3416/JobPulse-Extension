"""
飞书卡片交互回调服务 — 处理按钮点击事件

部署方式（任选其一）：
1. python callback_server.py           # 本地运行，配合 ngrok 暴露公网地址
2. 部署到 Vercel / Cloudflare Workers   # 无服务器方案

飞书回调配置：
  开放平台 → 应用 → 事件与回调 → 消息卡片 → 设置回调地址为 {公网URL}/callback
"""

import json
import os

from feishu import FeishuClient


def handle_card_action(payload: dict) -> dict:
    """
    处理卡片按钮回调
    飞书回调格式参考：https://open.feishu.cn/document/uAjLw4CM/ukzMukzMukzM/feishu-cards/card-action
    """
    action = payload.get("action", {})
    value = action.get("value", {})
    action_type = value.get("action")
    record_id = value.get("record_id")
    new_status = value.get("status")

    if action_type != "update_status" or not record_id:
        return {"code": 400, "msg": "无效的回调参数"}

    # 更新表格
    client = FeishuClient()

    # 同时更新「提醒状态」和「结果」字段
    fields = {}
    if new_status == "面试":
        fields["提醒状态"] = "有反馈"
        fields["结果"] = "面试"
    elif new_status == "被拒/无反馈":
        fields["提醒状态"] = "已失效"
        fields["结果"] = "无反馈"
    else:
        fields["提醒状态"] = "已跟进"

    ok = client.update_record(record_id, fields)
    if ok:
        return {
            "code": 0,
            "msg": "success",
            "card": {
                "type": "template",
                "data": {"template_id": get_success_card()},
            },
        }
    return {"code": 500, "msg": "更新失败"}


def get_success_card() -> str:
    """返回一个表示「已更新」的空模板 ID（需先在飞书开放平台创建）"""
    # 简化实现：直接返回 code 0，飞书会关闭卡片 loading 无额外动作
    return ""


# ── Flask 服务 ───────────────────────────────────────────


def create_app():
    try:
        from flask import Flask, request, jsonify

        app = Flask(__name__)

        @app.route("/callback", methods=["POST"])
        def callback():
            # 飞书回调的 body 在 action 字段中
            payload = request.get_json(force=True)
            # 飞书卡片回调格式可能是 {action: {value: {...}}} 或直接是 action 对象
            data = payload  # 飞书会在挑战时发送 challenge
            if "challenge" in payload:
                return jsonify({"challenge": payload["challenge"]})
            result = handle_card_action(data)
            return jsonify(result)

        return app
    except ImportError:
        return None


def run_flask():
    app = create_app()
    if app is None:
        print("⚠️ 未安装 Flask。请执行: pip install flask")
        print("或者直接集成到其他 Web 框架中。")
        print("\n回调处理函数 handle_card_action() 可以直接导入使用。")
        return
    port = int(os.environ.get("PORT", 8000))
    print(f"🚀 回调服务运行在 http://0.0.0.0:{port}/callback")
    print("   使用 ngrok 暴露公网: ngrok http 8000")
    app.run(host="0.0.0.0", port=port, debug=False)


if __name__ == "__main__":
    run_flask()
