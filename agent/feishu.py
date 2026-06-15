"""飞书 API 客户端"""

import time
import json
from typing import Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import (
    FEISHU_APP_ID,
    FEISHU_APP_SECRET,
    FEISHU_APP_TOKEN,
    FEISHU_TABLE_ID,
)

# Module-level token cache, shared across all FeishuClient instances
# to reduce token request frequency and SSL handshake chances.
_shared_token = None
_shared_token_expires_at = 0


def _session() -> requests.Session:
    """Create a session with retry strategy for transient failures (e.g. SSL EOF)."""
    sess = requests.Session()
    retry = Retry(
        total=2,
        backoff_factor=0.5,
        status_forcelist=[502, 503],
        allowed_methods=["GET", "POST", "PUT", "PATCH"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    sess.mount("https://", adapter)
    sess.mount("http://", adapter)
    return sess


class FeishuClient:
    TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    BITABLE_URL = "https://open.feishu.cn/open-apis/bitable/v1/apps"

    def __init__(self):
        self._session = _session()
        # Use shared module-level token cache
        self._token = _shared_token
        self._token_expires_at = _shared_token_expires_at

    # ── token 管理 ──────────────────────────────────────────

    def _get_token(self) -> str:
        global _shared_token, _shared_token_expires_at
        if time.time() < self._token_expires_at:
            return self._token

        # Retry once on SSL / transient errors
        last_err = None
        for attempt in range(2):
            try:
                resp = self._session.post(
                    self.TOKEN_URL,
                    json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
                    timeout=10,
                )
                data = resp.json()
                if data.get("code") != 0:
                    raise RuntimeError(f"获取 token 失败: [{data.get('code')}] {data.get('msg')}")
                token = data["tenant_access_token"]
                expires_at = time.time() + data.get("expire", 7200) - 60
                # Update both instance and module-level cache
                self._token = _shared_token = token
                self._token_expires_at = _shared_token_expires_at = expires_at
                return token
            except (requests.exceptions.SSLError, requests.exceptions.ConnectionError) as e:
                last_err = e
                if attempt == 0:
                    print(f"  ⚠️ Token 请求 SSL 错误，重试一次: {e}")
                    time.sleep(0.5)
                continue
        raise RuntimeError(f"获取 token 失败（重试后仍失败）: {last_err}")

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._get_token()}", "Content-Type": "application/json"}

    # ── 记录查询 ──────────────────────────────────────────

    def list_records(self, page_size: int = 100) -> list[dict]:
        """获取表格所有记录"""
        records = []
        page_token = None
        while True:
            params = {"page_size": page_size}
            if page_token:
                params["page_token"] = page_token
            url = f"{self.BITABLE_URL}/{FEISHU_APP_TOKEN}/tables/{FEISHU_TABLE_ID}/records"
            try:
                resp = self._session.get(url, headers=self._headers(), params=params, timeout=30)
            except requests.exceptions.RequestException as e:
                raise RuntimeError(f"查询记录网络错误: {e}")
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"查询记录失败: [{data.get('code')}] {data.get('msg')}")
            items = data.get("data", {}).get("items", [])
            records.extend(items)
            if not data.get("data", {}).get("has_more"):
                break
            page_token = data["data"].get("page_token")
        return records

    def get_record(self, record_id: str) -> dict:
        """获取单条记录"""
        url = f"{self.BITABLE_URL}/{FEISHU_APP_TOKEN}/tables/{FEISHU_TABLE_ID}/records/{record_id}"
        resp = self._session.get(url, headers=self._headers(), timeout=10)
        data = resp.json()
        if data.get("code") != 0:
            print(f"  ❌ 查询记录失败 [{data.get('code')}]: {data.get('msg')}")
            return {}
        return data.get("data", {}).get("record", {})

    def update_record(self, record_id: str, fields: dict) -> bool:
        """更新单条记录"""
        url = f"{self.BITABLE_URL}/{FEISHU_APP_TOKEN}/tables/{FEISHU_TABLE_ID}/records/{record_id}"
        resp = self._session.put(url, headers=self._headers(), json={"fields": fields}, timeout=10)
        data = resp.json()
        if data.get("code") != 0:
            print(f"  ❌ 更新记录失败 [{data.get('code')}]: {data.get('msg')}")
            return False
        return True

    def update_message_card(self, message_id: str, card: dict) -> bool:
        """更新已发送消息的卡片内容"""
        url = f"https://open.feishu.cn/open-apis/im/v1/messages/{message_id}"
        body = {
            "content": json.dumps(card, ensure_ascii=False),
            "msg_type": "interactive",
        }
        resp = self._session.patch(url, headers=self._headers(), json=body, timeout=10)
        data = resp.json()
        if data.get("code") != 0:
            print(f"  ❌ 更新消息卡片失败 [{data.get('code')}]: {data.get('msg')}")
            return False
        return True

    # ── 发送消息卡片 ──────────────────────────────────────

    def send_card(self, receive_id: str, card: dict, receive_id_type: str = "open_id"):
        """发送消息卡片给指定用户，成功时返回 message_id"""
        url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={receive_id_type}"
        body = {
            "receive_id": receive_id,
            "msg_type": "interactive",
            "content": json.dumps(card, ensure_ascii=False),
        }
        resp = self._session.post(url, headers=self._headers(), json=body, timeout=10)
        data = resp.json()
        if data.get("code") != 0:
            print(f"  ❌ 发送卡片失败 [{data.get('code')}]: {data.get('msg')}")
            return ""
        return data.get("data", {}).get("message_id", "")

    def send_card_via_webhook(self, webhook_url: str, card: dict):
        """通过 Webhook 发送卡片到群（无交互回调）"""
        resp = self._session.post(webhook_url, json={"msg_type": "interactive", "card": card}, timeout=10)
        return resp.status_code == 200

    # ── 字段值提取工具 ──────────────────────────────────

    @staticmethod
    def field_value(record: dict, field_name: str):
        """从飞书记录中提取字段值"""
        fields = record.get("fields", {})
        val = fields.get(field_name)
        if val is None:
            return ""
        if isinstance(val, dict):
            # 链接字段: {"link": url, "text": text}
            return val.get("link", val.get("text", ""))
        if isinstance(val, list):
            # 多选/单选: [{"text": "选项名"}] 或 ["选项名"]
            texts = []
            for item in val:
                if isinstance(item, dict):
                    texts.append(item.get("text", ""))
                else:
                    texts.append(str(item))
            return ", ".join(texts)
        return str(val)

    @staticmethod
    def extract_option_id(record: dict, field_name: str) -> str:
        """提取单选字段的 option_id（用于更新）"""
        fields = record.get("fields", {})
        val = fields.get(field_name)
        if isinstance(val, list) and len(val) > 0 and isinstance(val[0], dict):
            return val[0].get("id", "")
        return ""
