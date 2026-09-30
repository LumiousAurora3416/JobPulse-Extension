"""一次性迁移：把「待办」表里过长的事项拆成「事项」+「注意事项」

背景：v1.11.0 的邮件监控把「要做什么」和「注意事项」塞进了同一个字段（事项），
实测 37 条记录里事项中位数 68 字、最长 123 字，一眼看不出该干什么。
本脚本按新的字段要求重新拆分已有记录。

**只改「事项」「注意事项」两列**，截止时间 / 行动链接 / 已完成 / 邮件ID 一概不动。

用法：
  cd agent && python migrate_todo_summary.py --dry-run     # 只看拆分结果，不写表
  cd agent && python migrate_todo_summary.py               # 正式写表
"""

import argparse
import sys

import config
from feishu import FeishuClient
from llm_client import LLMClient

SHORT_ENOUGH = 20    # 事项短于这个字数，认为已是新格式，不再二次拆分

# 与 mail_watch.SYSTEM_PROMPT 的字段要求保持一致（那边判邮件，这边只拆已有文本）
SYSTEM_PROMPT = """你是待办整理助手。给你的是一条待办事项原文，它把"要做什么"和"注意事项"混在了一起。
把它拆成两部分，只输出 JSON：

- summary：只写"要做什么"，不超过 15 个字，像待办清单上的一行
  - 写法：动作 + 最小必要对象，如「参加美团在线笔试」「完成光大期货在线测评」
  - 不要写年份、场次、岗位方向、考试时长、设备要求——这些都归 note
- note：做的时候需要知道的注意事项；没有就留空字符串
  - 如「需全程开摄像头（手机作为第二监控机位）」「提前 15 分钟调试设备」
  - 不要重复 summary 里已经说过的动作本身

只输出 JSON，不要输出任何其他文字：
{"summary":"","note":""}"""


def main(argv=None):
    ap = argparse.ArgumentParser(description="拆分待办表的事项字段")
    ap.add_argument("--dry-run", action="store_true", help="只打印拆分结果，不写表")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 条（试跑用）")
    args = ap.parse_args(argv)

    if not config.LLM_API_KEY:
        print("❌ 未配置 LLM_API_KEY，无法拆分（本地放 agent/.env）")
        return 1

    client = FeishuClient(table_id=config.FEISHU_TODO_TABLE_ID)
    records = client.list_records()
    if args.limit:
        records = records[:args.limit]

    print(f"待办表共 {len(records)} 条    "
          f"{'【试跑，不写表】' if args.dry_run else '【正式写入】'}\n" + "=" * 70)

    llm = LLMClient()
    stats = {"split": 0, "skip": 0, "error": 0}

    for i, rec in enumerate(records, 1):
        rid = rec.get("record_id")
        raw = (client.field_value(rec, "事项") or "").strip()

        if not raw:
            stats["skip"] += 1
            continue
        if len(raw) <= SHORT_ENOUGH:
            stats["skip"] += 1
            print(f"[{i}/{len(records)}] ⏭ 已是短事项，跳过：{raw}")
            continue

        try:
            # temperature=0：这是一次性回填，要可复现
            verdict = llm.classify(SYSTEM_PROMPT, f"待办事项原文：{raw}", temperature=0)
        except Exception as e:
            stats["error"] += 1
            print(f"[{i}/{len(records)}] ⚠️ LLM 调用失败：{e}")
            continue

        summary = (verdict.get("summary") or "").strip()
        note = (verdict.get("note") or "").strip()
        if not summary:
            stats["error"] += 1
            print(f"[{i}/{len(records)}] ⚠️ 拆分结果为空，跳过")
            continue

        stats["split"] += 1
        # 打印完整原文：它同时充当一份可回查的备份（飞书记录历史也能恢复）
        print(f"[{i}/{len(records)}] 拆前（{len(raw)} 字）：{raw}")
        print(f"          事项 → {summary}")
        print(f"          注意 → {note[:70] or '（无）'}")
        print()

        if not args.dry_run:
            fields = {"事项": summary[:100]}
            if note:
                fields["注意事项"] = note[:500]
            client.update_record(rid, fields)

    print("=" * 70)
    print(f"拆分 {stats['split']} 条 | 跳过 {stats['skip']} 条 | 出错 {stats['error']} 条")
    if args.dry_run:
        print("\n这是试跑，没有写入任何数据。确认拆分质量后去掉 --dry-run 再跑一次。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
