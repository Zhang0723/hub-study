#!/usr/bin/env python3
"""每日监控：抓取新增 ESG 招标信息并生成推送日报。

流程：
  1. 从配置里的列表页抓取近期公告（只取最近 N 天）
  2. 与 data/seen.json 比对，跳过已推送过的 URL
  3. 对新公告做 LLM 结构化抽取
  4. 追加到 data/bids.json、更新 data/seen.json
  5. 生成 output/daily-<date>.md 与 output/daily-<date>.json

推送：把 output/daily-<date>.md 交给上层（Claude 用 SendMessage/邮件/webhook 推送），
或用 --webhook 直接 POST 到自定义地址。

用法：
    python monitor.py                          # 今日增量
    python monitor.py --days 3                 # 回看 3 天
    python monitor.py --webhook https://...    # 生成后推送到 webhook
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from collect import collect_candidates, extract_one  # noqa: E402
from config import load_config, load_seen, save_seen, match_keywords  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def render_daily(records: list[dict], day: str, stats: dict) -> str:
    L = [f"# ESG 招标信息日报 · {day}", ""]
    L.append(f"- 新增 **{len(records)}** 条 ｜ 抓取候选 {stats['candidates']} 条 "
             f"｜ 新 URL {stats['new_urls']} 条 ｜ 命中关键词 {stats['keyword_hits']} 条")
    L.append("")

    if not records:
        L.append("今日无新增 ESG 相关招标信息。")
        L.append("")
        return "\n".join(L)

    awards = [r for r in records if r.get("notice_type") == "中标公告"]
    bids = [r for r in records if r.get("notice_type") == "招标公告"]
    others = [r for r in records if r.get("notice_type") not in ("中标公告", "招标公告")]

    def block(title: str, items: list[dict]) -> None:
        if not items:
            return
        L.append(f"## {title}（{len(items)}）")
        L.append("")
        for r in items:
            amt = r.get("amount")
            amt_s = f"{amt:,.0f} 元" if isinstance(amt, (int, float)) and amt > 0 else "未披露/非固定金额"
            L.append(f"### {r.get('project_name') or r.get('title', '')}")
            L.append("")
            L.append(f"- 采购人：{r.get('buyer') or '-'}")
            L.append(f"- 中标方：{r.get('winner') or '-'}")
            L.append(f"- 金额：{amt_s}"
                     + (f"（{r['amount_basis']}）" if r.get("amount_basis") else ""))
            L.append(f"- 类别：{r.get('category', '-')} ｜ 地区：{r.get('region', '-')}")
            L.append(f"- 发布：{r.get('publish_date', '-')}")
            if r.get("esg_points"):
                L.append(f"- ESG 要点：{r['esg_points']}")
            L.append(f"- 链接：{r.get('url', '-')}")
            L.append("")

    block("一、中标公告", awards)
    block("二、招标公告（进行中）", bids)
    block("三、其他", others)

    L.append("---")
    L.append("")
    L.append("由 esg-tender-monitor skill 自动生成。")
    return "\n".join(L)


def push_webhook(url: str, markdown: str, day: str) -> bool:
    """POST 到 webhook。默认按飞书/钉钉通用的 markdown 文本消息格式。"""
    import requests

    payload = {
        "msg_type": "markdown",
        "markdown": {"content": f"**ESG 招标信息日报 {day}**\n\n{markdown[:3000]}"},
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        ok = r.status_code == 200
        print(f"webhook 推送: HTTP {r.status_code}")
        return ok
    except Exception as exc:  # noqa: BLE001
        print(f"webhook 推送失败: {exc}")
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="ESG 招标每日监控")
    ap.add_argument("--config", default="config/sources.yaml")
    ap.add_argument("--days", type=int, default=1, help="回看天数")
    ap.add_argument("--pages", type=int, default=2, help="每个列表页翻几页")
    ap.add_argument("--output-dir", default="output")
    ap.add_argument("--bids", default="data/bids.json")
    ap.add_argument("--seen", default="data/seen.json")
    ap.add_argument("--webhook", default="", help="生成后 POST 到该地址")
    ap.add_argument("--dry-run", action="store_true", help="只报告，不写文件")
    args = ap.parse_args()

    cfg = load_config(ROOT / args.config)
    today = date.today()
    since = (today - timedelta(days=args.days)).isoformat()

    seen = load_seen(ROOT / args.seen)
    print(f"已记录 {len(seen)} 条历史 URL")

    cands = collect_candidates(cfg, "list", args.pages, since, None)
    print(f"候选 {len(cands)} 条")

    # 关键词再过滤一次（list 模式已过滤，这里兜底 seed 混进来的情况）
    kw_hits = [c for c in cands if match_keywords(c.get("title", ""), cfg)]
    new_cands = [c for c in kw_hits if c["url"] not in seen]
    print(f"关键词命中 {len(kw_hits)} 条，其中新 URL {len(new_cands)} 条")

    if args.dry_run:
        for c in new_cands:
            print(f"  新: {c['title'][:60]}")
        return 0

    records: list[dict] = []
    for i, cand in enumerate(new_cands, 1):
        print(f"[{i}/{len(new_cands)}] {cand.get('title', '')[:52]}", flush=True)
        rec = extract_one(cand)
        if rec is None:
            print("    抽取失败")
            continue
        if not rec.get("is_esg_related"):
            print("    非 ESG 相关，跳过")
            seen.add(cand["url"])  # 已判定过，不再重复抓
            continue
        records.append(rec)
        seen.add(cand["url"])
        print(f"    OK {rec.get('publish_date')} [{rec.get('category')}] {rec.get('amount')}")
        time.sleep(0.5)

    # 追加到 bids.json
    bids_path = ROOT / args.bids
    existing: list[dict] = []
    if bids_path.exists():
        try:
            existing = json.loads(bids_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = []
    if isinstance(existing, dict):
        existing = existing.get("bids", [])
    existing.extend(records)
    bids_path.parent.mkdir(parents=True, exist_ok=True)
    bids_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    save_seen(ROOT / args.seen, seen)

    # 生成日报
    out_dir = ROOT / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    day = today.isoformat()
    md = render_daily(records, day, {
        "candidates": len(cands),
        "new_urls": len(new_cands),
        "keyword_hits": len(kw_hits),
    })
    (out_dir / f"daily-{day}.md").write_text(md, encoding="utf-8")
    (out_dir / f"daily-{day}.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n新增 {len(records)} 条 → {out_dir/f'daily-{day}.md'}")
    print(f"累计 {len(existing)} 条，seen 库 {len(seen)} 条")

    if args.webhook:
        push_webhook(args.webhook, md, day)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
