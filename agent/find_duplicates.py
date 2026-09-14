"""列出投递表里「公司 + 岗位」完全相同的重复记录（**只读，不删任何东西**）

用途：v1.9.1 插件加了写入查重，但历史上已经攒下的重复记录需要人工清理。
本脚本把每组重复的**区分信息**（结果 / 投递天数 / 匹配分 / 薪资 / JD 长度）列出来，
方便你判断留哪一条、删哪几条。

重复的判定规则与插件、Bot 完全一致：**公司 AND 岗位同时相同**才算重复；
同一家公司投了不同岗位**不算**（如 vivo 的 4 个不同产品经理岗）。

用法: cd agent && python3 find_duplicates.py
凭据来自 agent/.env。删除请到飞书网页端手动操作——本脚本不含任何写操作。

想打印可直接点开的记录链接，先设置租户域名：
  FEISHU_WEB_DOMAIN=你的租户.feishu.cn python3 find_duplicates.py
"""

import os
import sys
from collections import defaultdict
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from config import FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_APP_TOKEN, FEISHU_TABLE_ID

TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
RECORDS_URL = (
    f"https://open.feishu.cn/open-apis/bitable/v1/apps/{FEISHU_APP_TOKEN}"
    f"/tables/{FEISHU_TABLE_ID}/records"
)

# 可选：设置后打印可点开的记录链接；不设置就只打印 record_id
WEB_DOMAIN = os.environ.get("FEISHU_WEB_DOMAIN", "").strip()

# 结果靠后的排前面，方便一眼看出该组里"进展最远"的是哪条
RESULT_ORDER = [
    "offer", "三面挂", "二面挂", "一面挂", "面试", "测评", "简历挂",
    "无反馈", "放弃", "简历", "待投递",
]


def get_token():
    r = requests.post(
        TOKEN_URL,
        json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
        timeout=15,
    ).json()
    if r.get("code") != 0:
        raise RuntimeError(f"获取 token 失败: [{r.get('code')}] {r.get('msg')}")
    return r["tenant_access_token"]


def field_text(value):
    """把飞书字段值统一转成可读字符串（文本可能是 string / 数组 / 链接对象）。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        parts = []
        for x in value:
            if isinstance(x, dict):
                parts.append(x.get("text") or x.get("name") or "")
            else:
                parts.append(str(x))
        return "".join(parts).strip()
    if isinstance(value, dict):
        return (value.get("text") or value.get("link") or "").strip()
    return str(value)


def list_all_records(token):
    """分页拉全表（上限 20 页防死循环）。"""
    items, page_token = [], ""
    for _ in range(20):
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token
        r = requests.get(
            RECORDS_URL,
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=20,
        ).json()
        if r.get("code") != 0:
            raise RuntimeError(f"读取投递表失败: [{r.get('code')}] {r.get('msg')}")
        d = r["data"]
        items.extend(d.get("items", []))
        if not d.get("has_more") or not d.get("page_token"):
            break
        page_token = d["page_token"]
    return items


def record_link(record_id):
    if not WEB_DOMAIN:
        return ""
    return f"https://{WEB_DOMAIN}/base/{FEISHU_APP_TOKEN}?table={FEISHU_TABLE_ID}&record={record_id}"


def main():
    print("== JobPulse 重复记录清单（只读，不会删除任何东西）==\n")

    if not (FEISHU_APP_ID and FEISHU_APP_SECRET and FEISHU_APP_TOKEN and FEISHU_TABLE_ID):
        print("❌ agent/.env 缺少飞书配置")
        sys.exit(1)

    token = get_token()
    records = list_all_records(token)
    print(f"📡 共读取 {len(records)} 条记录\n")

    groups = defaultdict(list)
    for rec in records:
        f = rec.get("fields", {})
        company = field_text(f.get("公司"))
        position = field_text(f.get("岗位"))
        if company and position:
            groups[(company, position)].append(rec)

    dups = {k: v for k, v in groups.items() if len(v) > 1}

    if not dups:
        print("✅ 没有重复记录")
        return

    extra = sum(len(v) - 1 for v in dups.values())
    print(f"⚠️ 找到 {len(dups)} 组重复，多出 {extra} 条记录\n")

    for i, ((company, position), recs) in enumerate(
        sorted(dups.items(), key=lambda kv: -len(kv[1])), 1
    ):
        # 按"结果进展"排序，进展最远的排前面；结果相同时投递天数多的（更早那次）排前面
        def sort_key(rec):
            f = rec.get("fields", {})
            result = field_text(f.get("结果"))
            order = RESULT_ORDER.index(result) if result in RESULT_ORDER else 99
            try:
                days = -float(field_text(f.get("投递天数")) or 0)
            except ValueError:
                days = 0
            return (order, days)

        recs = sorted(recs, key=sort_key)

        print("─" * 72)
        print(f"[{i}] {company} — {position}   （{len(recs)} 条，需删 {len(recs) - 1} 条）")
        print("─" * 72)
        print(f"    {'结果':<8}{'投递天数':<10}{'匹配分':<8}{'薪资':<14}{'JD':<6} record_id")
        for rec in recs:
            f = rec.get("fields", {})
            rid = rec.get("record_id", "")
            jd_len = len(field_text(f.get("岗位JD")))
            print(
                f"    {field_text(f.get('结果')) or '—':<8}"
                f"{field_text(f.get('投递天数')) or '—':<10}"
                f"{field_text(f.get('匹配分')) or '—':<8}"
                f"{(field_text(f.get('薪资')) or '—')[:12]:<14}"
                f"{(str(jd_len) if jd_len else '无'):<6} {rid}"
            )
            if WEB_DOMAIN:
                print(f"           {record_link(rid)}")
        print()

    print("─" * 72)
    print("怎么判断留哪条：")
    print("  · 同一组里结果不同的 → 通常保留**进展最靠后**的那条（上面已按此排序，第一条即最靠后）")
    print("  · 结果完全相同的   → 留哪条都行；优先留「匹配分 / 薪资 / JD」信息更全的那条")
    print("  · 删除请到飞书网页端手动操作（本脚本只读，不含任何写操作）")
    if not WEB_DOMAIN:
        print()
        print("💡 想打印可直接点开的记录链接，加环境变量再跑一次：")
        print("   FEISHU_WEB_DOMAIN=你的租户.feishu.cn python3 find_duplicates.py")


if __name__ == "__main__":
    main()
