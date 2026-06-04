"""JobPulse Agent 配置
优先级：环境变量 > 下方默认值
将本文件复制为 config.local.py 并填入敏感信息，避免提交到仓库
"""

import os


def env(key, default=""):
    return os.environ.get(key, default)


# ========== 飞书配置 ==========
FEISHU_APP_ID = env("FEISHU_APP_ID", "YOUR_APP_ID")
FEISHU_APP_SECRET = env("FEISHU_APP_SECRET", "YOUR_APP_SECRET")
FEISHU_APP_TOKEN = env("FEISHU_APP_TOKEN", "YOUR_APP_TOKEN")
FEISHU_TABLE_ID = env("FEISHU_TABLE_ID", "YOUR_TABLE_ID")

# 飞书用户/群组 ID（发消息给谁）
# 可在飞书 Open API 调试台获取，或直接用 Webhook 地址
# 如果填 "" 则尝试从 FEISHU_WEBHOOK 发送
FEISHU_RECEIVER_ID = "YOUR_OPEN_ID"          # 飞书 user / open_id
FEISHU_RECEIVER_TYPE = "open_id" # user_id | open_id | chat_id
FEISHU_WEBHOOK = ""              # 群机器人 Webhook 地址（可选）

# ========== LLM 配置（BYOK） ==========
LLM_API_KEY = ""          # 你的 API Key
LLM_API_BASE = "https://api.openai.com/v1"  # 兼容 OpenAI 格式的接口
LLM_MODEL = "gpt-4o"      # 模型名
# 如果你用 Claude API，可改为：
# LLM_API_BASE = "https://api.anthropic.com/v1"
# LLM_MODEL = "claude-sonnet-4-20250514"

# ========== Agent 行为配置 ==========
# 投递超过多少天触发提醒（小时）
FOLLOW_UP_HOURS = 72

# 是否启用 LLM 归因分析
ENABLE_ANALYSIS = True

# 归因分析执行间隔（单位：天；0 = 每次运行都执行）
ANALYSIS_INTERVAL_DAYS = 7
