#!/usr/bin/env python3
"""采集 ESG/可持续发展/双碳相关招标与中标公告，抽取结构化记录。

两条采集通道：
  1. list  —— 从省级镜像列表页翻页，标题关键词过滤（覆盖近期，河北最完整）
  2. seed  —— 从 urls.jsonl 读取已知 URL（Claude 用 WebSearch 发现的历史/跨省公告）

输出 data/bids.json（结构化记录）与 data/bids_raw.jsonl（原始正文，便于复核）。

用法：
    python collect.py --mode list --pages 8
    python collect.py --mode seed --input data/urls.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_page import fetch  # noqa: E402
from llm import chat_json  # noqa: E402
from parse_hebei import parse_announcement  # noqa: E402
from config import load_config, match_keywords, load_seen  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

SYSTEM = """你是招投标数据分析专家，负责从公告正文抽取结构化字段。
要求：
1. 只依据正文，绝不编造。正文没有的信息一律填 null。
2. amount 单位是元，纯数字；多标包要合计，并在 amount_basis 里写清怎么加总的。
3. 若正文写的是"节能收益分成""费率""服务费比例"等非固定金额，amount 填 null，
   amount_basis 写实际口径（例如"按节能收益 83.6% 分成"）。
4. category 从给定列表中选一个；都不符合选"其他"。
5. is_esg_related 判断是否与 ESG / 可持续发展 / 双碳 / 绿色低碳 / 碳排放 / 环保相关。
6. 全中文。"""

PROMPT = """从下面的招标公告正文中抽取结构化信息，严格输出 JSON。

字段说明：
- notice_type: 公告类型，取值 "招标公告" 或 "中标公告" 或 "其他"
- project_name: 项目名称
- buyer: 采购人/招标人
- winner: 中标(成交)供应商；招标公告没有则填 null
- amount: 中标/成交金额（元，纯数字）；不是固定金额则 null
- amount_basis: 金额口径说明
- publish_date: 发布日期 YYYY-MM-DD
- category: 项目类别，从 [ESG报告编制, 碳足迹核算, 碳排放核查, 节能降碳改造,
  绿色工厂认证, 绿色供应链, 碳资产管理, 碳普惠, 低碳咨询规划, 环保检测,
  循环经济, 其他] 中选一个
- is_esg_related: 布尔
- esg_points: 该项目涉及的 ESG 要点，1-2 句
- region: 采购人所在省市

正文：
{doc}

JSON："""


def extract_list_items(html: str, base_url: str, since: str = "") -> list[dict]:
    """从列表页抽出 (url, title, date)。日期优先取 URL 里的 tYYYYMMDD。"""
    items: list[dict] = []
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    anchor_re = re.compile(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
    date_re = re.compile(r"(20\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})")

    for m in anchor_re.finditer(html):
        href, title = m.group(1), re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(2))).strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")) or len(title) < 8:
            continue
        if title in seen_titles:
            continue
        url = urljoin(base_url, href)
        dm = re.search(r"t(20\d{2})(\d{2})(\d{2})", url)
        if dm:
            d = f"{dm.group(1)}-{dm.group(2)}-{dm.group(3)}"
        else:
            tm = date_re.search(html[m.end(): m.end() + 300])
            if not tm:
                continue
            d = f"{int(tm.group(1)):04d}-{int(tm.group(2)):02d}-{int(tm.group(3)):02d}"
        if since and d < since:
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        seen_titles.add(title)
        items.append({"url": url, "title": title, "date_hint": d})
    return items


def collect_candidates(cfg: dict, mode: str, pages: int, since: str,
                       input_path: Path | None) -> list[dict]:
    cands: list[dict] = []
    seen: set[str] = set()

    if mode == "seed":
        if not input_path or not input_path.exists():
            print(f"seed 模式需要 --input，{input_path} 不存在")
            return cands
        for line in input_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("url") and obj["url"] not in seen:
                seen.add(obj["url"])
                cands.append(obj)
        print(f"seed 模式：{len(cands)} 条候选")
        return cands

    for src in cfg.get("sources", []):
        if not src.get("enabled", True):
            continue
        for p in range(pages):
            base = src["list_url"]
            url = base if p == 0 else base.rstrip("/") + f"/index_{p}.html"
            res = fetch(url, retries=2, raw=True)
            if not res["ok"]:
                print(f"  {src['name']} p{p}: {res.get('error')}")
                break
            items = extract_list_items(res["html"], url, since)
            hits = [it for it in items if match_keywords(it["title"], cfg)]
            print(f"  {src['name']} p{p}: {len(items)} 条 → ESG 命中 {len(hits)}")
            for it in hits:
                if it["url"] in seen:
                    continue
                seen.add(it["url"])
                it["source"] = src["name"]
                cands.append(it)
            time.sleep(src.get("delay", 2))
            if not hits and not items:
                break
    return cands


def extract_one(cand: dict, client_hint: str = "") -> dict | None:
    page = fetch(cand["url"], raw=True)
    if not page["ok"]:
        return None
    # 河北站两种页面格式统一解析；其他站点退回纯文本
    text = parse_announcement(page.get("html", "")) or page["text"]
    if len(text) < 300:
        return None
    try:
        rec = chat_json(
            PROMPT.format(doc=text[:9000]),
            system=SYSTEM,
            temperature=0.1,
            max_tokens=1200,
        )
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(rec, dict):
        return None
    rec["url"] = cand["url"]
    rec["title"] = cand.get("title") or rec.get("project_name") or ""
    rec["source"] = cand.get("source", "")
    rec["fetched_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    rec.setdefault("is_esg_related", False)
    return rec


def main() -> int:
    ap = argparse.ArgumentParser(description="采集 ESG 相关招投标公告")
    ap.add_argument("--mode", choices=["list", "seed"], default="list")
    ap.add_argument("--config", default="config/sources.yaml")
    ap.add_argument("--input", default="data/urls.jsonl")
    ap.add_argument("--output", default="data/bids.json")
    ap.add_argument("--raw-output", default="data/bids_raw.jsonl")
    ap.add_argument("--pages", type=int, default=8)
    ap.add_argument("--since", default="", help="只收该日期之后发布的")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--skip-seen", action="store_true", help="跳过已入库的 URL")
    args = ap.parse_args()

    cfg = load_config(ROOT / args.config)
    seen_urls = load_seen(ROOT / "data" / "seen.json") if args.skip_seen else set()

    in_path = ROOT / args.input if not Path(args.input).is_absolute() else Path(args.input)
    cands = collect_candidates(cfg, args.mode, args.pages, args.since, in_path)
    if seen_urls:
        before = len(cands)
        cands = [c for c in cands if c["url"] not in seen_urls]
        print(f"去重：{before} → {len(cands)}")
    if args.limit:
        cands = cands[: args.limit]

    print(f"\n开始抽取 {len(cands)} 条")
    records: list[dict] = []
    for i, cand in enumerate(cands, 1):
        print(f"[{i}/{len(cands)}] {cand.get('title', '')[:52]}", flush=True)
        rec = extract_one(cand)
        if rec is None:
            print("    抽取失败")
            continue
        if not rec.get("is_esg_related"):
            print("    非 ESG 相关，跳过")
            continue
        records.append(rec)
        print(f"    OK {rec.get('publish_date')} [{rec.get('category')}] "
              f"{rec.get('amount')} {rec.get('notice_type')}")
        time.sleep(0.5)

    out_path = ROOT / args.output if not Path(args.output).is_absolute() else Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

    raw_path = ROOT / args.raw_output if not Path(args.raw_output).is_absolute() else Path(args.raw_output)
    with raw_path.open("a", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\n入库 {len(records)} 条 → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
