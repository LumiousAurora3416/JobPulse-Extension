"""求职邮件监控：读 QQ 邮箱 → LLM 判定 → 写入「待办」表

入表判据是「需要你本人做一个动作 + 有时限」，不是「是不是求职邮件」。
实测投递回执 / 拒信 / 招聘广告会占掉疑似求职邮件的大头，必须排除（见 SYSTEM_PROMPT）。

安全：邮箱全程只读（select(readonly=True) + BODY.PEEK[]），不会把邮件标记成已读。

用法：
  cd agent && python mail_watch.py --dry-run --limit 20   # 试跑 20 封，只看判定不写表
  cd agent && python mail_watch.py --dry-run              # 全量判定，仍不写表
  cd agent && python mail_watch.py                        # 判定并写表
"""

import argparse
import email
import hashlib
import imaplib
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

import config
from feishu import FeishuClient
from llm_client import LLMClient

BODY_CHARS = 1500        # 送进 LLM 的正文长度，够判断即可（太长白烧 token）
# 要读的文件夹。Junk 也读：招聘邮件被误判进垃圾箱是常事，漏掉一封测评邀请的代价太大
MAIL_FOLDERS = ["INBOX", "Junk"]
TODO_TYPES = ["测评", "笔试", "面试", "完善资料", "其他"]  # 必须与 init_match_tables.TODO_TYPE_OPTIONS 一致
CST = timezone(timedelta(hours=8))   # 邮件时间一律按北京时间理解

SYSTEM_PROMPT = """你是求职邮件助理。判断一封邮件是否需要**用户本人去做一件事**，并提取结构化信息。

【入待办的标准】以下两条必须同时满足：
1. 需要用户本人做一个动作：参加/完成面试、测评、笔试，或去补交、完善材料
2. 这件事有时间要求：有截止时间，或必须在某个时间段内完成

【必须排除，不要入待办】
- 投递回执：感谢投递、简历已收到、简历投递成功（用户没有任何事要做）
- 拒信、感谢信：很遗憾、暂不匹配、流程结束
- 招聘广告、岗位推荐、双选会/宣讲会邀请：诚邀您投递、为您推荐、火热进行中
- 对方的承诺：我们会在 N 个工作日内联系您（这是对方的动作，不是用户的截止时间）
- 验证码、账单、订阅通知、学校或银行日常通知
- 非秋招流程的事务：离职证明签署、入职手续、在职相关通知
- 校园大使招募、校园大使信息采集
- 日历提醒邮件：正文极短（只有"参加 XX 的面试/笔试"这类一句话），
  且既没有截止时间也没有操作链接——这类是日历重复提醒，正式通知在另一封邮件里

【字段要求】
- type 只能取：测评 / 笔试 / 面试 / 完善资料 / 其他
- deadline：绝对时间，格式 "YYYY-MM-DD HH:MM"，按北京时间（UTC+8）
  - 原文是时间区间（如"9-23 00:00 至 9-25 23:59"）→ 取右端点
  - 原文是"X 个工作日内"→ 从邮件发送时间推算，跳过周六周日
  - 没有明确时间要求 → null，不要猜
- summary：一句话说清"要做什么"，并带上原文里的注意事项（如"需全程开摄像头""每题作答 3 分钟"）
- action_url：用户要点的那个链接（测评入口 / 面试入口 / 填表链接）
  - 排除：退订 unsubscribe、隐私政策、官网首页、公众号、招聘系统首页
  - 找不到合适的 → null
- company / position：邮件提到的公司名、岗位名，没有就留空字符串

只输出 JSON，不要输出任何其他文字：
{"actionable":true,"skip_reason":"","company":"","position":"","type":"测评","summary":"","deadline":null,"deadline_raw":"","action_url":null}"""


# ── 邮件解析 ──────────────────────────────────────────────

def decode_mime(raw):
    """邮件头是 MIME 编码的（=?UTF-8?B?...?=），解回可读文本"""
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return str(raw)


def message_date(msg):
    """解析邮件头 Date，解析失败返回 None（宁可不过滤，也别误丢邮件）"""
    raw = msg.get("Date")
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
    except Exception:
        return None
    if dt is None:
        return None
    if dt.tzinfo is None:          # 有些邮件不带时区，按 UTC 处理
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(CST)


def message_id(msg):
    """去重键。少数邮件没有 Message-ID，用「主题+时间+发件人」做一个稳定替代值"""
    mid = (msg.get("Message-ID") or "").strip()
    if mid:
        return mid[:200]
    seed = f"{msg.get('Subject')}|{msg.get('Date')}|{msg.get('From')}"
    return "sha1:" + hashlib.sha1(seed.encode("utf-8", "replace")).hexdigest()


def _payload_text(part):
    data = part.get_payload(decode=True)
    if data is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return data.decode(charset, errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


def html_to_text(html):
    """剥标签取正文。

    关键：先把 <a href="URL">文字</a> 换成「文字 (URL)」再剥标签——
    否则剥完标签 URL 就没了，action_url 永远提不出来。
    """
    html = re.sub(
        r"(?is)<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
        lambda m: f"{re.sub(r'(?s)<[^>]+>', '', m.group(2))} ({m.group(1)})",
        html,
    )
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"),
                 ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'")):
        html = html.replace(a, b)
    return re.sub(r"[ \t　]+", " ", html)


def extract_body(msg, limit=BODY_CHARS):
    """取正文纯文本：优先 text/plain，没有再从 text/html 剥标签"""
    text = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                text = _payload_text(part)
                if text.strip():
                    break
        if not text.strip():
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    text = html_to_text(_payload_text(part))
                    if text.strip():
                        break
    elif msg.get_content_type() == "text/html":
        text = html_to_text(_payload_text(msg))
    else:
        text = _payload_text(msg)

    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)          # 压缩连续空行
    text = re.sub(r"[ \t　]{2,}", " ", text)
    return text.strip()[:limit]


def fetch_folder(box, folder, since):
    """读一个文件夹，返回邮件列表（全程只读，不标已读）

    QQ 邮箱的 IMAP 不认 SINCE 日期筛选（实测一律返回全量），
    所以这里取序号最大的 N 封（IMAP 序号按时间递增，最新的在末尾），
    再用邮件头里的 Date 在本地过滤。
    """
    typ, _ = box.select(folder, readonly=True)      # 只读：不标已读、不改状态
    if typ != "OK":
        print(f"  ⚠️ 打不开文件夹 {folder}，跳过")
        return []

    typ, data = box.search(None, "ALL")
    ids = data[0].split()
    kept = ids[-config.MAIL_FETCH_LIMIT:]
    print(f"  {folder}: 共 {len(ids)} 封，回看最新 {len(kept)} 封")

    out = []
    for num in kept:
        typ, raw = box.fetch(num, "(BODY.PEEK[])")   # PEEK：不标已读
        if typ != "OK" or not raw or not isinstance(raw[0], tuple):
            continue
        msg = email.message_from_bytes(raw[0][1])
        dt = message_date(msg)
        if dt is not None and dt < since:
            continue                        # 本地日期过滤
        out.append({
            "date": dt,
            "folder": folder,
            "subject": decode_mime(msg.get("Subject")),
            "sender": decode_mime(msg.get("From")),
            "message_id": message_id(msg),
            "body": extract_body(msg),
        })
    return out


def fetch_emails(since):
    """遍历要读的文件夹，返回按时间升序、已按 Message-ID 去重的邮件列表"""
    box = imaplib.IMAP4_SSL(config.MAIL_IMAP_HOST, 993)
    box.login(config.MAIL_USER, config.MAIL_AUTH_CODE)
    try:
        mails = []
        for folder in MAIL_FOLDERS:
            mails.extend(fetch_folder(box, folder, since))
    finally:
        try:
            box.logout()
        except Exception:
            pass

    epoch = datetime(1970, 1, 1, tzinfo=CST)
    mails.sort(key=lambda m: m["date"] or epoch)

    # 同一封邮件理论上可能同时出现在多个文件夹，这里按 Message-ID 去重
    seen, unique = set(), []
    for m in mails:
        if m["message_id"] in seen:
            continue
        seen.add(m["message_id"])
        unique.append(m)
    return unique


# ── 判定与写表 ────────────────────────────────────────────

def build_prompt(mail):
    when = f"{mail['date']:%Y-%m-%d %H:%M}" if mail["date"] else "未知"
    return (
        f"邮件发送时间：{when}（北京时间）\n"
        f"发件人：{mail['sender']}\n"
        f"主题：{mail['subject']}\n"
        f"正文：\n{mail['body']}"
    )


def parse_deadline(value):
    """LLM 给的 'YYYY-MM-DD HH:MM' → 飞书要的毫秒时间戳；解析不了返回 None"""
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(str(value).strip(), fmt)
            return int(dt.replace(tzinfo=CST).timestamp() * 1000)
        except ValueError:
            continue
    return None


def build_fields(mail, verdict):
    """组装写入「待办」表的字段。空值不写，避免飞书对 None 的处理差异。

    单选列（待办类型）写入未定义的选项会 FieldConvFail 且**整条记录失败**，
    所以这里再做一道白名单校验。
    """
    fields = {
        "事项": (verdict.get("summary") or "").strip()[:500],
        "已完成": False,
        "邮件ID": mail["message_id"],
        "邮件主题": mail["subject"][:200],
    }
    company = (verdict.get("company") or "").strip()
    position = (verdict.get("position") or "").strip()
    if company:
        fields["公司"] = company[:100]
    if position:
        fields["岗位"] = position[:100]

    vtype = (verdict.get("type") or "").strip()
    fields["待办类型"] = vtype if vtype in TODO_TYPES else "其他"

    ms = parse_deadline(verdict.get("deadline"))
    if ms:
        fields["截止时间"] = ms
    if mail["date"]:
        fields["邮件发送时间"] = int(mail["date"].timestamp() * 1000)

    url = (verdict.get("action_url") or "").strip()
    if url.startswith("http"):
        # 链接字段的记录值格式与文本不同，必须是 {"link":…, "text":…}
        fields["行动链接"] = {"link": url, "text": "打开"}

    return fields


def existing_message_ids(client):
    """读「待办」表已有的邮件 ID，用于去重"""
    try:
        records = client.list_records()
    except Exception as e:
        print(f"  ⚠️ 读取待办表失败，本次不做去重（可能重复写入）: {e}")
        return set()
    ids = set()
    for rec in records:
        val = FeishuClient.field_value(rec, "邮件ID")
        if val:
            ids.add(str(val).strip())
    return ids


def main(argv=None):
    ap = argparse.ArgumentParser(description="求职邮件 → 待办")
    ap.add_argument("--dry-run", action="store_true", help="只打印判定结果，不写表")
    ap.add_argument("--limit", type=int, default=0, help="只处理最新的 N 封邮件（试跑用）")
    ap.add_argument("--since", default="",
                    help=f"起始日期 YYYY-MM-DD（默认：最近 {config.MAIL_WINDOW_DAYS} 天）")
    args = ap.parse_args(argv)

    if not (config.MAIL_USER and config.MAIL_AUTH_CODE):
        print("❌ 未配置 MAIL_USER / MAIL_AUTH_CODE（本地放 agent/.env，云端放 GitHub Secrets）")
        return 1

    if not config.LLM_API_KEY:
        # 缺 key 时直接退出，不要逐封报错：那样循环会跑完并返回 0，
        # 在 Actions 里表现为「绿灯通过、其实一封没处理」，比直接失败更难发现
        print("❌ 未配置 LLM_API_KEY，无法判定邮件（本地放 agent/.env，云端放 GitHub Secrets）")
        return 1

    try:
        floor = datetime.strptime(config.MAIL_START_DATE, "%Y-%m-%d").replace(tzinfo=CST)
        if args.since:
            since = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=CST)
        else:
            since = datetime.now(CST) - timedelta(days=config.MAIL_WINDOW_DAYS)
        since = max(since, floor)     # 硬下限：防止误传 --since 把整个邮箱拉一遍
    except ValueError:
        print(f"❌ 日期格式应为 YYYY-MM-DD，收到：{args.since}")
        return 1

    print(f"邮箱：{config.MAIL_USER}    起始：{since:%Y-%m-%d %H:%M}"
          f"    {'【试跑，不写表】' if args.dry_run else '【正式写入】'}\n")

    try:
        mails = fetch_emails(since)
    except imaplib.IMAP4.error as e:
        print(f"❌ 邮箱登录/读取失败：{e}")
        return 1

    if args.limit:
        mails = mails[-args.limit:]
    print(f"日期范围内 {len(mails)} 封\n")

    todo_client = FeishuClient(table_id=config.FEISHU_TODO_TABLE_ID)
    known = existing_message_ids(todo_client)
    print(f"待办表已有 {len(known)} 条记录（按邮件 ID 去重）\n" + "=" * 70)

    llm = LLMClient()
    stats = {"todo": 0, "skip": 0, "dup": 0, "error": 0}
    hit_ms = int(time.time() * 1000)

    for i, mail in enumerate(mails, 1):
        when = f"{mail['date']:%m-%d %H:%M}" if mail["date"] else "??-?? ??:??"
        # 来自垃圾箱的特别标出来，方便核对是不是误判
        tag = "" if mail["folder"] == "INBOX" else f"[{mail['folder']}] "
        head = f"[{i}/{len(mails)}] {when}  {tag}{mail['subject'][:34]}"

        if mail["message_id"] in known:
            stats["dup"] += 1
            print(f"{head}  ⏭ 已处理过")
            continue

        try:
            # temperature=0：截止时间要逐字准，0.1 会让同一封邮件两次跑出不同结果
            verdict = llm.classify(SYSTEM_PROMPT, build_prompt(mail), temperature=0)
        except Exception as e:
            stats["error"] += 1
            print(f"{head}  ⚠️ LLM 调用失败：{e}")
            continue

        if not verdict.get("actionable"):
            stats["skip"] += 1
            print(f"{head}  ❌ {verdict.get('skip_reason') or '无需用户行动'}")
            continue

        stats["todo"] += 1
        fields = build_fields(mail, verdict)
        dl = fields.get("截止时间")
        dl_text = (datetime.fromtimestamp(dl / 1000, CST).strftime("%m-%d %H:%M")
                   if dl else "无截止")
        print(f"{head}  ✅ {fields['待办类型']}  截止={dl_text}")
        print(f"        {fields['事项'][:110]}")
        raw = (verdict.get("deadline_raw") or "").strip()
        if raw:
            # 打印原文，方便人工核对推算出来的截止时间对不对
            print(f"        截止原文：{raw[:80]}")
        if "行动链接" in fields:
            print(f"        链接：{fields['行动链接']['link'][:100]}")

        if not args.dry_run:
            rid = todo_client.create_record(fields)
            if not rid:
                stats["error"] += 1
                print("        ⚠️ 写入失败")

    print("\n" + "=" * 70)
    print(f"入待办 {stats['todo']} 封 | 不入 {stats['skip']} 封 | "
          f"已处理过 {stats['dup']} 封 | 出错 {stats['error']} 封")
    print(f"耗时 {int((time.time() * 1000 - hit_ms) / 1000)} 秒")
    if args.dry_run:
        print("\n这是试跑，没有写入任何数据。确认判定准确后去掉 --dry-run 再跑一次。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
