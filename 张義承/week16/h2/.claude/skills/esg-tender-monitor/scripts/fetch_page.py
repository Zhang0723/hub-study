#!/usr/bin/env python3
"""抓取网页正文并存为纯文本。

与 h1 skill 里的同名脚本一致：本机 WebFetch 对政务站点不可用，统一走本地 HTTP。

用法：
    python fetch_page.py URL
    python fetch_page.py URL --out page.txt
    python fetch_page.py URL --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time

import requests

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

DROP_TAGS = r"script|style|noscript|iframe|svg|head|nav|footer|header|form"
BR_TAGS = r"br|p|div|tr|li|h[1-6]|section|article|td|th"


def decode(raw: bytes) -> str:
    head = raw[:2048].decode("ascii", "ignore")
    m = re.search(r'charset=["\']?\s*([\w-]+)', head, re.I)
    if m:
        enc = m.group(1).lower()
        if enc in ("gb2312", "gbk"):
            enc = "gb18030"
        try:
            return raw.decode(enc, "ignore")
        except LookupError:
            pass
    for enc in ("utf-8", "gb18030", "big5"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "ignore")


def html_to_text(html: str) -> tuple[str, str]:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else ""

    s = re.sub(rf"<({DROP_TAGS})\b.*?</\1>", " ", html, flags=re.S | re.I)
    s = re.sub(rf"</?({BR_TAGS})\b[^>]*>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = s.replace("&nbsp;", " ").replace("&#160;", " ").replace("&amp;", "&")
    s = s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')

    lines = []
    for line in s.split("\n"):
        line = re.sub(r"[ \t\xa0]+", " ", line).strip()
        if line:
            lines.append(line)

    out: list[str] = []
    for line in lines:
        if not out or out[-1] != line:
            out.append(line)
    return title, "\n".join(out)


def fetch(url: str, *, timeout: int = 30, retries: int = 3, raw: bool = False) -> dict:
    """抓取页面。raw=True 时额外返回原始 HTML（解析列表页链接/结构化数据时需要）。

    注意：JS 渲染的页面正文（去标签后的文本）可能很短，但 HTML 里有完整数据。
    所以 raw=True 时只用原始字节数判断成功，不看正文长度。
    """
    last = ""
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
            if r.status_code == 200 and len(r.content) > 400:
                html = decode(r.content)
                title, text = html_to_text(html)
                ok = len(r.content) > 2000 if raw else len(text) > 200
                if ok:
                    res = {"url": url, "final_url": r.url, "title": title,
                           "text": text, "bytes": len(r.content), "ok": True}
                    if raw:
                        res["html"] = html
                    return res
                last = f"正文过短({len(text)}字/{len(r.content)}B)"
            else:
                last = f"HTTP {r.status_code}/{len(r.content)}B"
        except requests.RequestException as exc:
            last = type(exc).__name__
        time.sleep(2 + 3 * attempt)
    return {"url": url, "ok": False, "error": last, "text": "", "title": ""}


def main() -> int:
    ap = argparse.ArgumentParser(description="抓取网页正文")
    ap.add_argument("url")
    ap.add_argument("--out")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--timeout", type=int, default=30)
    args = ap.parse_args()

    res = fetch(args.url, timeout=args.timeout)
    if not res["ok"]:
        print(f"抓取失败: {res.get('error')}", file=sys.stderr)
        return 1

    if args.json:
        res.pop("ok", None)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0

    body = res["text"]
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(body)
        print(f"{args.out}  {len(body)} 字  {res['title']}")
    else:
        print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
