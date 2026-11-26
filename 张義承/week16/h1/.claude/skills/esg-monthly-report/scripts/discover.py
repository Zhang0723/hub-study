#!/usr/bin/env python3
"""从可直连的列表页发现候选网页，产出 urls.jsonl。

为什么需要它：本机 WebFetch 工具对政务/企业站点普遍不可用（域名安全校验失败），
所以"发现"这一步用"WebSearch + 本地列表页抓取"两条腿走路：
  1. Claude 用 WebSearch 拿到跨板块的候选 URL，写进 data/urls.jsonl；
  2. 本脚本从可直连的列表页批量抽取标题/日期/链接，补齐 WebSearch 覆盖不到的条目。

用法：
    python discover.py --client shenhua --output data/urls.jsonl --append
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_page import fetch, decode  # noqa: E402
import requests  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# 板块 -> 列表页。全部是实测可直连的列表页（政务站点把发布日期编进文件名 tYYYYMMDD，
# 解析时优先从 URL 取日期）。
SECTIONS = [
    {
        "section": "policy",
        "source": "生态环境部-应对气候变化与碳市场",
        "url": "https://www.mee.gov.cn/ywgz/ydqhbh/",
    },
    {
        "section": "policy",
        "source": "生态环境部-法律法规与标准",
        "url": "https://www.mee.gov.cn/ywgz/fgbz/",
    },
    {
        "section": "policy",
        "source": "生态环境部-部内要闻",
        "url": "https://www.mee.gov.cn/ywdt/hjywnews/",
    },
    {
        "section": "industry",
        "source": "国家发改委-新闻发布",
        "url": "https://www.ndrc.gov.cn/xwdt/xwfb/",
    },
]

DATE_RE = re.compile(r"(20\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})")
ANCHOR_RE = re.compile(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)


def clean(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html)).strip()


def extract_items(page_html: str, base_url: str, min_year: int = 2020) -> list[dict]:
    """在列表页里找 (链接, 标题, 日期)。

    日期优先取 URL 里的 tYYYYMMDD（政务站点几乎都把发布日期编进文件名，最可靠），
    取不到才退回链接后面的文本日期。相邻的重复标题只保留一条。
    """
    items: list[dict] = []
    seen: set[str] = set()
    seen_titles: set[str] = set()
    for m in ANCHOR_RE.finditer(page_html):
        href, inner = m.group(1), clean(m.group(2))
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        if len(inner) < 8 or inner in seen_titles:
            continue

        url = urljoin(base_url, href)
        dm = None
        um = re.search(r"t(20\d{2})(\d{2})(\d{2})", url)
        if um:
            dm = (int(um.group(1)), int(um.group(2)), int(um.group(3)))
        else:
            tm = DATE_RE.search(page_html[m.end(): m.end() + 300])
            if tm:
                dm = (int(tm.group(1)), int(tm.group(2)), int(tm.group(3)))
        if not dm:
            continue

        y, mo, d = dm
        if not (min_year <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31):
            continue

        key = (url, inner)
        if key in seen:
            continue
        seen.add(key)
        seen_titles.add(inner)
        items.append({
            "url": url,
            "title": inner,
            "date_hint": f"{y:04d}-{mo:02d}-{d:02d}",
        })
    return items


def month_range(period: str) -> list[str]:
    """返回从 period 起往前推的月份列表，形如 ['202611', '202610', '202609']。"""
    y, m = int(period[:4]), int(period[5:7])
    out = []
    for _ in range(3):
        out.append(f"{y:04d}{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="从列表页发现候选网页")
    ap.add_argument("--client", default="shenhua")
    ap.add_argument("--period", default="")
    ap.add_argument("--output", default="data/urls.jsonl")
    ap.add_argument("--append", action="store_true")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config" / "clients.yaml").read_text(encoding="utf-8"))
    client = cfg["clients"][args.client]
    terms = " ".join(client.get("aliases", [])[:3])

    today = date.today()
    period = args.period or f"{today.year - (1 if today.month == 1 else 0)}-{(today.month - 2) % 12 + 1:02d}"

    rows: list[dict] = []
    for sec in SECTIONS:
        url = sec["url"]
        res = fetch(url, retries=2, raw=True)
        if not res["ok"]:
            print(f"  跳过 {sec['source']}: {res.get('error')}")
            continue
        items = extract_items(res["html"], url)
        # 只保留报告周期内的条目；列表页常混有更早的归档
        cutoff = period + "-01"
        fresh = [it for it in items if it["date_hint"] >= cutoff]
        print(f"  {sec['source']}: {len(items)} 条，其中 {len(fresh)} 条在 {period} 之后")
        for it in fresh:
            it["source"] = sec["source"]
            it["section"] = sec["section"]
            rows.append(it)
        time.sleep(1)

    out_path = ROOT / args.output if not Path(args.output).is_absolute() else Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    seen_urls = set()
    if args.append and out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    seen_urls.add(json.loads(line)["url"])
                except (json.JSONDecodeError, KeyError):
                    pass

    mode = "a" if args.append else "w"
    written = 0
    with out_path.open(mode, encoding="utf-8") as fh:
        for r in rows:
            if r["url"] in seen_urls:
                continue
            seen_urls.add(r["url"])
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            written += 1

    print(f"\n新增 {written} 条候选 -> {out_path}（{len(seen_urls)} 条去重后合计）")
    print("提示：这些是政策/行业板块的候选。客户与对标企业板块请用 WebSearch 补充 URL 后追加。")
    print(f"      建议搜索词：{terms} ESG 报告 评级 / {terms} 碳排放 公告 / "
          f"{client['peers'][0]} ESG 报告 2026")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
