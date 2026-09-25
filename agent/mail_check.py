"""QQ邮箱只读巡检脚本（一次性调试工具，不属于正式流程）

用途：连 IMAP 拉最近 N 天邮件，打印 发件人 / 主题 / 日期 / 正文摘要，
      用来观察真实求职邮件长什么样，据此设计解析规则（收件域名、截止时间写法）。

安全约束（重要）：
  - select(readonly=True)   只读打开收件箱
  - fetch 用 BODY.PEEK[]    拉取正文但不把邮件标记成「已读」
  - 不写飞书表、不落任何文件  纯打印

用法：
  cd agent && python mail_check.py        # 默认最近 7 天
  cd agent && python mail_check.py 3      # 最近 3 天
"""

import email
import imaplib
import re
import sys
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

import config

# 最多回看多少封邮件（按序号取最新的 N 封，防止一次拉爆）
_TOTAL_FETCH_LIMIT = 150

# 只用来给人快速定位，不做判定。真正的判定留给后面的 LLM
_JOB_KEYWORDS = ["测评", "笔试", "面试", "简历", "投递", "申请", "offer", "录用",
                 "招聘", "在线测试", "候选人", "人才", "实习", "校招", "社招", "邀请"]


def message_date(msg):
    """解析邮件头里的 Date，解析失败返回 None（宁可不过滤，也别误丢邮件）"""
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
    return dt.astimezone()         # 转成本地时区，方便和 since 比较


def decode_mime(raw):
    """邮件头是 MIME 编码的（=?UTF-8?B?...?=），解回可读文本"""
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return str(raw)


def _payload_text(part):
    """取出某个 MIME 部分的正文文本"""
    data = part.get_payload(decode=True)
    if data is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return data.decode(charset, errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


def _html_to_text(html):
    """粗暴剥标签：只是看正文大意，不需要严谨的 HTML 解析"""
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"),
                 ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'")):
        html = html.replace(a, b)
    return re.sub(r"[ \t　]+", " ", html)


def extract_body(msg, limit=200):
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
                    text = _html_to_text(_payload_text(part))
                    if text.strip():
                        break
    elif msg.get_content_type() == "text/html":
        text = _html_to_text(_payload_text(msg))
    else:
        text = _payload_text(msg)

    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"\n{2,}", "\n", text)           # 压缩连续空行
    text = re.sub(r"[ \t　]{2,}", " ", text)
    return text.strip()[:limit]


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else config.MAIL_LOOKBACK_DAYS

    if not config.MAIL_USER or not config.MAIL_AUTH_CODE:
        print("❌ 未配置 MAIL_USER / MAIL_AUTH_CODE（请写入 agent/.env）")
        return 1

    host = config.MAIL_IMAP_HOST
    # 带上时区：邮件头解析出来的时间是 aware 的，naive 和 aware 不能直接比大小
    since = datetime.now().astimezone() - timedelta(days=days)
    print(f"服务器：{host}:993    邮箱：{config.MAIL_USER}")
    print(f"范围  ：{since:%Y-%m-%d} 起（最近 {days} 天）\n")

    try:
        box = imaplib.IMAP4_SSL(host, 993)
    except Exception as e:
        print(f"❌ 连不上 {host}：{e}")
        return 1

    try:
        box.login(config.MAIL_USER, config.MAIL_AUTH_CODE)
        print("✅ 登录成功\n")
    except imaplib.IMAP4.error as e:
        print(f"❌ 登录失败：{e}")
        print("   排查方向：")
        print("     ① 邮箱地址是否完整（IMAP 登录名要用完整地址，不是 QQ 号）")
        print("     ② 授权码是否已失效（重新生成会让旧码立即作废）")
        print("     ③ 该域名的 IMAP 服务器地址是否正确")
        return 1

    try:
        # readonly=True：不改动收件箱状态（不标已读、不移动邮件）
        box.select("INBOX", readonly=True)

        # ⚠️ QQ 邮箱的 IMAP 不认 SINCE（实测 SINCE 一律返回全量），
        # 所以不用服务器端筛选：取序号最大的 N 封（IMAP 序号按时间递增，
        # 最新的在末尾），再用邮件头里的 Date 在本地过滤
        typ, data = box.search(None, "ALL")
        all_ids = data[0].split()
        ids = all_ids[-_TOTAL_FETCH_LIMIT:]
        print(f"INBOX 共 {len(all_ids)} 封，回看最新 {len(ids)} 封")
        print(f"本地筛出 {since:%Y-%m-%d} 之后的邮件")
        print("=" * 70)

        job_count = 0
        shown = 0
        for num in ids:
            # BODY.PEEK[] 而不是 RFC822：PEEK 不会把邮件标记成已读
            typ, raw = box.fetch(num, "(BODY.PEEK[])")
            if typ != "OK" or not raw or not isinstance(raw[0], tuple):
                continue
            msg = email.message_from_bytes(raw[0][1])

            dt = message_date(msg)
            if dt is not None and dt < since:
                continue                       # 本地日期过滤：太老的跳过

            shown += 1
            subject = decode_mime(msg.get("Subject"))
            sender = decode_mime(msg.get("From"))
            body = extract_body(msg)

            hits = [k for k in _JOB_KEYWORDS if k in subject or k in body]
            if hits:
                job_count += 1

            stamp = f"{dt:%Y-%m-%d %H:%M}" if dt else "(日期无法解析)"
            print(f"\n[{shown}] {stamp}")
            print(f"    发件人：{sender}")
            print(f"    主题  ：{subject}")
            if hits:
                print(f"    疑似求职 ✅ 命中：{'、'.join(hits[:6])}")
            print(f"    正文  ：{body}")

        print("\n" + "=" * 70)
        print(f"日期范围内 {shown} 封，其中疑似求职 {job_count} 封")
        print("\n下一步：看这些邮件的发件域名、主题写法、截止时间的表述方式，")
        print("       据此决定解析规则（哪些域名要收、'3个工作日内' 这类怎么归一化）。")
        return 0
    finally:
        try:
            box.logout()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
