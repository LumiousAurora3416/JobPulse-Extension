"""一次性初始化脚本：岗位匹配度 V1 的飞书表结构

职责（全部是「只新建、不改已有字段」，幂等可重复执行）：
  1. 在当前 JobPulse base（FEISHU_APP_TOKEN）下创建「简历库」表（若已存在则复用），
     并补齐字段：简历名称 / 适用方向(单选) / 简历正文 / 来源版本 / 更新时间
  2. 若简历库为空且本地存在 resume.txt，写入 1 行种子（当前主简历）
  3. 给投递表（FEISHU_TABLE_ID）新增「匹配分」数字列（不存在才加）

用法: cd agent && python init_match_tables.py
凭据来自 agent/.env（config.py 自动加载）。不要放进 Render 部署链。
"""

import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from config import FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_APP_TOKEN, FEISHU_TABLE_ID

# ---- Feishu endpoints ----
BASE = "https://open.feishu.cn/open-apis"
TOKEN_URL = f"{BASE}/auth/v3/tenant_access_token/internal"
BITABLE = f"{BASE}/bitable/v1/apps"

# ---- Bitable field type codes ----
T_TEXT = 1        # 多行文本（记录值传 string）
T_NUMBER = 2      # 数字（记录值传 number）
T_SINGLE = 3      # 单选（记录值传「选项名字符串」）
T_DATE = 5        # 日期（记录值传毫秒时间戳）
T_LASTMOD = 1002  # 最后更新时间（自动字段，不可手动写值）

RESUME_TABLE_NAME = "简历库"
RESUME_FIELDS = [
    {"field_name": "简历名称", "type": T_TEXT},
    {
        "field_name": "适用方向",
        "type": T_SINGLE,
        "property": {
            "options": [
                {"name": "通用"},
                {"name": "产品"},
                {"name": "前端"},
                {"name": "后端"},
                {"name": "算法"},
                {"name": "其他"},
            ]
        },
    },
    {"field_name": "简历正文", "type": T_TEXT},
    {"field_name": "来源版本", "type": T_TEXT},
    # 更新时间：优先自动字段 1002；API 若拒绝则回退普通日期 5（由调用方写值）
    {"field_name": "更新时间", "type": T_LASTMOD},
]


def api_get(token, url):
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=15)
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"GET {url} 失败: [{data.get('code')}] {data.get('msg')}")
    return data


def api_post(token, url, body):
    r = requests.post(
        url,
        json=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=15,
    )
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"POST {url} 失败: [{data.get('code')}] {data.get('msg')}")
    return data


def get_token():
    r = requests.post(
        TOKEN_URL,
        json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
        timeout=10,
    )
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取 token 失败: [{data.get('code')}] {data.get('msg')}")
    return data["tenant_access_token"]


def list_table_names(token):
    """返回 {table_name: table_id}。飞书列表接口分页，这里全量拉一遍表结构清单。"""
    items, page_token = [], None
    while True:
        url = f"{BITABLE}/{FEISHU_APP_TOKEN}/tables?page_size=100"
        if page_token:
            url += f"&page_token={page_token}"
        data = api_get(token, url)
        items.extend(data["data"]["items"])
        if not data["data"].get("has_more"):
            break
        page_token = data["data"]["page_token"]
    return {it["name"]: it["table_id"] for it in items}


def find_or_create_resume_table(token, tables):
    if RESUME_TABLE_NAME in tables:
        print(f"  ✔ 已存在「{RESUME_TABLE_NAME}」表: {tables[RESUME_TABLE_NAME]}")
        return tables[RESUME_TABLE_NAME]
    # 建表 body 需 default_view_name + 至少 1 个字段；其余字段随后用 ensure 补齐
    body = {
        "table": {
            "name": RESUME_TABLE_NAME,
            "default_view_name": "简历库视图",
            "fields": [RESUME_FIELDS[0]],  # 简历名称
        }
    }
    data = api_post(token, f"{BITABLE}/{FEISHU_APP_TOKEN}/tables", body)
    tid = data["data"]["table_id"]
    print(f"  ✔ 已创建「{RESUME_TABLE_NAME}」表: {tid}")
    return tid


def list_field_names(token, table_id):
    items, page_token = [], None
    while True:
        url = f"{BITABLE}/{FEISHU_APP_TOKEN}/tables/{table_id}/fields?page_size=100"
        if page_token:
            url += f"&page_token={page_token}"
        data = api_get(token, url)
        items.extend(data["data"]["items"])
        if not data["data"].get("has_more"):
            break
        page_token = data["data"]["page_token"]
    return {it["field_name"]: it for it in items}


def ensure_field(token, table_id, spec):
    """字段不存在才新增；返回 (field_name, 实际 type)。"""
    existing = list_field_names(token, table_id)
    name = spec["field_name"]
    if name in existing:
        print(f"  · 字段已存在，跳过: {name}")
        return name, existing[name]["type"]

    field_type = spec["type"]
    body = {"field_name": name, "type": field_type}
    if spec.get("property"):
        body["property"] = spec["property"]

    # 自动字段（1002 最后更新时间）在部分版本不允许通过 API 建列 → 回退普通日期 5
    if field_type == T_LASTMOD:
        try:
            api_post(token, f"{BITABLE}/{FEISHU_APP_TOKEN}/tables/{table_id}/fields", body)
            print(f"  ✔ 新增字段: {name} (type=1002 自动更新时间)")
            return name, T_LASTMOD
        except RuntimeError as e:
            print(f"  ⚠ 自动更新时间建列失败，回退普通日期字段: {e}")
            body = {"field_name": name, "type": T_DATE}
            api_post(token, f"{BITABLE}/{FEISHU_APP_TOKEN}/tables/{table_id}/fields", body)
            print(f"  ✔ 新增字段: {name} (type=5 日期，回退)")
            return name, T_DATE

    api_post(token, f"{BITABLE}/{FEISHU_APP_TOKEN}/tables/{table_id}/fields", body)
    print(f"  ✔ 新增字段: {name} (type={field_type})")
    return name, field_type


def record_count(token, table_id):
    data = api_get(
        token, f"{BITABLE}/{FEISHU_APP_TOKEN}/tables/{table_id}/records?page_size=1"
    )
    return data["data"]["total"]


def seed_resume(token, table_id, ut_field_type):
    """简历库为空且本地有 resume.txt 时写入一行种子。"""
    if record_count(token, table_id) > 0:
        print("  · 简历库非空，跳过种子写入")
        return
    resume_file = Path(__file__).parent / "resume.txt"
    if not resume_file.exists():
        print("  ⚠ 本地未找到 resume.txt，只建结构不写种子（后续可在网页端手动加行）")
        return

    fields = {
        "简历名称": "主简历·原始版",
        "适用方向": "通用",  # 单选字段：传选项名字符串
        "简历正文": resume_file.read_text(encoding="utf-8"),
        "来源版本": "",
    }
    # 自动更新时间字段(1002)无需写值；回退的普通日期(5)需要毫秒时间戳
    if ut_field_type == T_DATE:
        fields["更新时间"] = int(time.time() * 1000)
    api_post(
        token,
        f"{BITABLE}/{FEISHU_APP_TOKEN}/tables/{table_id}/records",
        {"fields": fields},
    )
    print(f"  ✔ 已写入种子简历（来源 agent/resume.txt，{resume_file.stat().st_size} 字节）")


def ensure_match_score_column(token):
    """给投递表加「匹配分」数字列（只新建，不影响任何已有列）。"""
    existing = list_field_names(token, FEISHU_TABLE_ID)
    if "匹配分" in existing:
        print(f"  · 投递表已有「匹配分」列，跳过")
        return
    api_post(
        token,
        f"{BITABLE}/{FEISHU_APP_TOKEN}/tables/{FEISHU_TABLE_ID}/fields",
        {"field_name": "匹配分", "type": T_NUMBER},
    )
    print(f"  ✔ 投递表已新增「匹配分」数字列")


def main():
    print("== JobPulse 匹配度 V1 · 飞书表结构初始化 ==")
    if not (FEISHU_APP_ID and FEISHU_APP_SECRET and FEISHU_APP_TOKEN and FEISHU_TABLE_ID):
        print("❌ agent/.env 缺少飞书配置（FEISHU_APP_ID/SECRET/APP_TOKEN/TABLE_ID）")
        sys.exit(1)

    token = get_token()
    print("✔ token 获取成功\n")

    # 1) 简历库表
    print("— 简历库表 —")
    tables = list_table_names(token)
    resume_tid = find_or_create_resume_table(token, tables)

    # 2) 补齐字段；记住「更新时间」实际类型，供种子行决定是否写时间戳
    print("— 简历库字段 —")
    ut_type = T_TEXT
    for spec in RESUME_FIELDS[1:]:
        _, real = ensure_field(token, resume_tid, spec)
        if spec["field_name"] == "更新时间":
            ut_type = real
    print(f"  · 「更新时间」实际类型: {ut_type}")

    # 3) 种子
    print("— 种子简历 —")
    seed_resume(token, resume_tid, ut_type)

    # 4) 投递表加「匹配分」列
    print("— 投递表加列 —")
    ensure_match_score_column(token)

    print("\n== 完成 ==")
    print(f"简历库 table_id = {resume_tid}")
    print("（插件设置页「简历库 Table ID」可留空，会自动按表名查找）")


if __name__ == "__main__":
    main()
