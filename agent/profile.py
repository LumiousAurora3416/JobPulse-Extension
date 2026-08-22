"""JobPulse 长期记忆画像（跨会话保留用户偏好）

与 memory.py 的区别：
- memory.py 存对话轮次（会被裁剪到最近 5 轮）
- 本模块存用户长期偏好（不裁剪、跨会话保留），如「主要投前端」「坐标杭州」

存储：agent/user_profile.json
结构：{sender_id: {"profile": {key: value}, "updated_at": ts}}

沿用 memory.py 的 Lock + 原子写模式，但使用独立文件与独立锁。
"""

import json
import os
import threading
import time

STORE_PATH = os.path.join(os.path.dirname(__file__), "user_profile.json")
_lock = threading.Lock()
MAX_FACTS = 30          # 每用户最多保留 30 条偏好，防止无限膨胀
VALUE_MAX_LEN = 200     # 单条 value 上限


def _load() -> dict:
    """Load store. 文件不存在 / 损坏时返回 {}。"""
    if not os.path.exists(STORE_PATH):
        return {}
    try:
        with open(STORE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict):
    """原子写入：先写临时文件再替换，避免写坏。"""
    tmp = STORE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STORE_PATH)


def get_profile(sender_id: str) -> dict:
    """返回该用户的 {profile: {...}, updated_at}；无记录返回 {}。"""
    with _lock:
        data = _load()
        return data.get(sender_id) or {}


def upsert_facts(sender_id: str, facts: list) -> dict:
    """合并 [{key, value}, ...] 到用户画像。

    - 同 key 覆盖（用户新说「现在主要投后端」覆盖旧「前端」）
    - 过滤空 key/value，单条 value 截断到 VALUE_MAX_LEN
    - 超过 MAX_FACTS 时保留最新条目
    返回合并后的 profile dict。
    """
    with _lock:
        data = _load()
        entry = data.get(sender_id) or {"profile": {}, "updated_at": 0}
        profile = dict(entry.get("profile") or {})
        for f in facts:
            key = (f.get("key") or "").strip()
            value = (f.get("value") or "").strip()
            if not key or not value:
                continue
            profile[key] = value[:VALUE_MAX_LEN]
        if len(profile) > MAX_FACTS:
            profile = dict(list(profile.items())[-MAX_FACTS:])
        entry["profile"] = profile
        entry["updated_at"] = int(time.time())
        data[sender_id] = entry
        _save(data)
        return profile


def clear_profile(sender_id: str):
    """清空该用户的长期画像。"""
    with _lock:
        data = _load()
        data.pop(sender_id, None)
        _save(data)


def format_profile(profile: dict) -> str:
    """压缩成 LLM 可读的一句话，如 '目标方向：前端；所在城市：杭州'。"""
    if not profile:
        return ""
    return "；".join(f"{k}：{v}" for k, v in profile.items())
