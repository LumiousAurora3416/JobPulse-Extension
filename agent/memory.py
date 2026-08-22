"""JobPulse 多轮对话记忆（短期记忆，按用户存储最近 N 轮）

存储：agent/conversation_store.json
结构：{open_id: {"history": [{role, content}...], "updated_at": ts}}

只存「用户输入 + 最终自然语言回复」，不存中间工具消息。
回调服务是多线程后台，所有读写用模块级锁保护，防止并发写坏 JSON。
"""

import json
import os
import threading
import time

STORE_PATH = os.path.join(os.path.dirname(__file__), "conversation_store.json")
MAX_MESSAGES = 10  # 每用户最多保留 10 条（5 轮）
_lock = threading.Lock()


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


def _trim(history: list) -> list:
    """裁剪到 MAX_MESSAGES 条；若末尾是孤立 user 则丢弃，保证以 assistant 结尾。"""
    if len(history) > MAX_MESSAGES:
        history = history[-MAX_MESSAGES:]
    while history and history[-1].get("role") == "user":
        history.pop()
    return history


def append_turn(sender_id: str, user_msg: str, assistant_msg: str):
    """记录一轮完整对话（user + assistant）。任一侧为空则不写。"""
    if not user_msg or not assistant_msg:
        return
    with _lock:
        data = _load()
        entry = data.get(sender_id) or {"history": [], "updated_at": 0}
        entry["history"] = _trim(entry["history"] + [
            {"role": "user", "content": user_msg},
            {"role": "assistant", "content": assistant_msg},
        ])
        entry["updated_at"] = int(time.time())
        data[sender_id] = entry
        _save(data)


def get_history(sender_id: str) -> list:
    """返回该用户的历史消息列表 [{role, content}...]，已裁剪且配对。"""
    with _lock:
        data = _load()
        entry = data.get(sender_id) or {}
        history = entry.get("history") or []
        return _trim(list(history))


def clear(sender_id: str):
    """清空该用户的对话记忆。"""
    with _lock:
        data = _load()
        data.pop(sender_id, None)
        _save(data)
