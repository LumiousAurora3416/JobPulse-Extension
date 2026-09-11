#!/bin/bash
# JobPulse 一键启动（回调服务 + ngrok）
# 使用：bash start.sh

echo "🚀 JobPulse 启动中..."

# 切换到项目目录
cd "$(dirname "$0")/agent" || exit 1

# 启动回调服务（后台）
python3 callback_server.py &
CALLBACK_PID=$!
echo "  ✅ 回调服务已启动 (PID: $CALLBACK_PID)"

# 等待 Flask 就绪
sleep 2

# 启动 ngrok（后台）
if command -v ngrok &> /dev/null; then
    ngrok http 8000 --log=stdout > /tmp/ngrok.log &
    NGROK_PID=$!
    sleep 3
    # 提取 ngrok 公网地址
    NGROK_URL=$(curl -s http://127.0.0.1:4040/api/tunnels | grep -oP 'https://[^"]+\.ngrok-free\.dev' | head -1)
    echo "  ✅ ngrok 已启动 (PID: $NGROK_PID)"
    echo "  📌 公网地址: $NGROK_URL"
    echo "  📌 飞书回调地址: ${NGROK_URL}/callback"
else
    echo "  ⚠️ 未安装 ngrok，请手动启动: ngrok http 8000"
fi

echo ""
echo "📋 按 Ctrl+C 停止所有服务"

# 等待 Ctrl+C
trap "kill $CALLBACK_PID $NGROK_PID 2>/dev/null; echo '已停止'; exit" INT
wait
