"""JobPulse Agent 配置
优先级：环境变量 > .env 文件 > 下方默认值
运行时自动加载 agent/.env（仅限本地，不上传 GitHub）
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    # Load .env from the same directory as this config file
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass  # dotenv not installed, rely on env vars only


def env(key, default=""):
    return os.environ.get(key, default)


# ========== 飞书配置（必须通过环境变量设置） ==========
FEISHU_APP_ID = env("FEISHU_APP_ID")           # 飞书自建应用 App ID
FEISHU_APP_SECRET = env("FEISHU_APP_SECRET")   # 飞书自建应用 App Secret
FEISHU_APP_TOKEN = env("FEISHU_APP_TOKEN")     # 多维表格 Base Token
FEISHU_TABLE_ID = env("FEISHU_TABLE_ID")       # 多维表格 Table ID（投递表）
FEISHU_TRACK_TABLE_ID = env("FEISHU_TRACK_TABLE_ID")  # 插件埋点表 Table ID（留空则丢弃埋点）
# 「待办」表 Table ID（邮件监控写入）。表 ID 不是密钥，给个默认值省得每处都配
FEISHU_TODO_TABLE_ID = env("FEISHU_TODO_TABLE_ID", "tblmclGkCNe8eSLo")

# 飞书用户/群组 ID（发消息给谁）
# 可在飞书 Open API 调试台获取，或直接用 Webhook 地址
# 如果填 "" 则尝试从 FEISHU_WEBHOOK 发送
FEISHU_RECEIVER_ID = env("FEISHU_RECEIVER_ID")                # 飞书 user / open_id
FEISHU_RECEIVER_TYPE = "open_id" # user_id | open_id | chat_id
FEISHU_WEBHOOK = ""              # 群机器人 Webhook 地址（可选）

# ========== 邮箱监控（求职邮件 → 待办） ==========
# 授权码 = 邮箱的完整读取权限，只走环境变量 / GitHub Secrets，绝不写进代码
MAIL_USER = env("MAIL_USER")              # 完整邮箱地址（IMAP 登录名要用完整地址）
MAIL_AUTH_CODE = env("MAIL_AUTH_CODE")    # 16 位授权码（不是 QQ 密码）
# 留成可覆盖：foxmail.com 别名等场景可能要换 IMAP 服务器
MAIL_IMAP_HOST = env("MAIL_IMAP_HOST", "imap.qq.com")
MAIL_LOOKBACK_DAYS = int(env("MAIL_LOOKBACK_DAYS", "7"))    # mail_check.py 用：拉取最近几天
# mail_watch.py 用：只处理这个日期之后的邮件（首次回填的范围下限）
MAIL_START_DATE = env("MAIL_START_DATE", "2026-09-01")
# QQ IMAP 不支持 SINCE 筛选，只能先取最新的 N 封，再按 Date 在本地过滤
MAIL_FETCH_LIMIT = int(env("MAIL_FETCH_LIMIT", "300"))

# ========== LLM 配置（BYOK，均可通过环境变量覆盖） ==========
LLM_API_KEY = env("LLM_API_KEY", "")                           # 你的 API Key
LLM_API_BASE = env("LLM_API_BASE", "https://api.openai.com/v1")  # 兼容 OpenAI 格式的接口
LLM_MODEL = env("LLM_MODEL", "gpt-4o")                           # 模型名
# 如果你用 Claude API，可改为：
# LLM_API_BASE = "https://api.anthropic.com/v1"
# LLM_MODEL = "claude-sonnet-4-20250514"

# ========== Agent 行为配置 ==========
# ⚠️ 已废弃（v1.9.0 起改用下方三项）：投递超过多少小时触发提醒。
# 暂时保留以免破坏现有 import，追踪逻辑切换完成后删除。
FOLLOW_UP_HOURS = 72

# 跟进提醒节奏（v1.9.0「结果」状态机重构）
FOLLOW_UP_FIRST_DAYS = int(env("FOLLOW_UP_FIRST_DAYS", "5"))        # 首次提醒：投递后第几天
FOLLOW_UP_INTERVAL_DAYS = int(env("FOLLOW_UP_INTERVAL_DAYS", "7"))  # 之后每几天复催一次
FOLLOW_UP_MAX_CARDS = int(env("FOLLOW_UP_MAX_CARDS", "10"))         # 单次运行最多推几张卡片

# 是否启用 LLM 归因分析
ENABLE_ANALYSIS = True

# 归因分析执行间隔（单位：天；0 = 每次运行都执行）
ANALYSIS_INTERVAL_DAYS = 7

# ========== 岗位匹配度（--match） ==========
MATCH_THRESHOLD = int(env("MATCH_THRESHOLD", "70"))          # 匹配度 ≥ 此值判「可投」
MATCH_WEIGHTS = {"硬性门槛": 0.2, "技能匹配": 0.4, "经历相关性": 0.4}  # 维度权重（契约 §7.2）
MATCH_MAX_JD_CHARS = int(env("MATCH_MAX_JD_CHARS", "2000"))         # JD 截断长度
MATCH_MAX_RESUME_CHARS = int(env("MATCH_MAX_RESUME_CHARS", "4000")) # 简历截断长度
