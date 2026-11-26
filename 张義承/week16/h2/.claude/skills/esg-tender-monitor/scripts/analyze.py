#!/usr/bin/env python3
"""分析 ESG 招投标数据：热点分布与中标金额分布。

输入 data/bids.json（或多个 json 分片），输出 analysis/summary.md + analysis/summary.json。

用法：
    python analyze.py --input data/bids.json --output-dir analysis
    python analyze.py --input data/bids.json --since 2024-11-26
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_bids(paths: list[Path]) -> list[dict]:
    bids: list[dict] = []
    seen: set[str] = set()
    for p in paths:
        if not p.exists():
            print(f"跳过不存在的文件 {p}")
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = data.get("bids", [])
        for b in data:
            url = b.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            bids.append(b)
    return bids


def parse_date(s: str) -> date | None:
    try:
        return date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def bucket_of(amount: float, buckets: list[dict]) -> str:
    for b in buckets:
        lo = b.get("min")
        hi = b.get("max")
        if (lo is None or amount >= lo) and (hi is None or amount < hi):
            return b["name"]
    return "未知"


def analyze(bids: list[dict], buckets: list[dict]) -> dict:
    total = len(bids)
    with_amount = [b for b in bids if isinstance(b.get("amount"), (int, float))
                   and b["amount"] > 0]
    amounts = [float(b["amount"]) for b in with_amount]

    # 热点：按类别 / 按采购人 / 按中标方 / 按地区 / 按公告类型
    def top(key: str, n: int = 10) -> list[tuple[str, int]]:
        c = Counter()
        for b in bids:
            v = b.get(key)
            if isinstance(v, list):
                for x in v:
                    if x:
                        c[str(x)] += 1
            elif v:
                c[str(v)] += 1
        return c.most_common(n)

    # 按年份
    by_year: dict[str, int] = Counter()
    amount_by_year: dict[str, float] = defaultdict(float)
    for b in bids:
        d = parse_date(b.get("publish_date", ""))
        if d:
            by_year[str(d.year)] += 1
            if isinstance(b.get("amount"), (int, float)):
                amount_by_year[str(d.year)] += float(b["amount"])

    # 金额分档
    dist = Counter()
    amount_by_bucket: dict[str, list[float]] = defaultdict(list)
    for b in with_amount:
        name = bucket_of(float(b["amount"]), buckets)
        dist[name] += 1
        amount_by_bucket[name].append(float(b["amount"]))

    ordered_buckets = [b["name"] for b in buckets]
    distribution = []
    for name in ordered_buckets:
        vals = amount_by_bucket.get(name, [])
        distribution.append({
            "bucket": name,
            "count": dist.get(name, 0),
            "ratio": round(dist.get(name, 0) / len(with_amount), 4) if with_amount else 0,
            "total_amount": sum(vals),
            "median": round(statistics.median(vals), 2) if vals else None,
        })

    return {
        "total_bids": total,
        "with_amount": len(with_amount),
        "amount_coverage": round(len(with_amount) / total, 4) if total else 0,
        "amount_sum": sum(amounts),
        "amount_mean": round(statistics.mean(amounts), 2) if amounts else None,
        "amount_median": round(statistics.median(amounts), 2) if amounts else None,
        "amount_max": max(amounts) if amounts else None,
        "amount_min": min(amounts) if amounts else None,
        "by_category": top("category", 15),
        "by_buyer": top("buyer", 10),
        "by_winner": top("winner", 10),
        "by_region": top("region", 10),
        "by_notice_type": top("notice_type", 5),
        "by_year": sorted(by_year.items()),
        "amount_by_year": {k: round(v, 2) for k, v in sorted(amount_by_year.items())},
        "amount_distribution": distribution,
    }


def render_markdown(s: dict, bids: list[dict], period_note: str) -> str:
    L: list[str] = []
    L.append("# ESG 招投标汇总分析")
    L.append("")
    L.append(f"> {period_note}")
    L.append("")
    L.append("## 一、总量概览")
    L.append("")
    L.append(f"- 公告总数：**{s['total_bids']}** 条")
    L.append(f"- 有效金额：**{s['with_amount']}** 条（覆盖率 {s['amount_coverage']:.0%}）")
    if s["amount_sum"]:
        L.append(f"- 金额合计：**{s['amount_sum']:,.0f} 元**（约 {s['amount_sum']/1e4:,.1f} 万元）")
        L.append(f"- 单笔均值：{s['amount_mean']:,.0f} 元 ｜ 中位数：{s['amount_median']:,.0f} 元")
        L.append(f"- 单笔区间：{s['amount_min']:,.0f} ~ {s['amount_max']:,.0f} 元")
    L.append("")

    L.append("## 二、热点招标情况")
    L.append("")
    L.append("### 按项目类别")
    L.append("")
    L.append("| 类别 | 数量 |")
    L.append("|------|------|")
    for name, cnt in s["by_category"]:
        L.append(f"| {name} | {cnt} |")
    L.append("")

    for title, key in [("按采购人", "by_buyer"), ("按中标供应商", "by_winner"),
                       ("按地区", "by_region"), ("按公告类型", "by_notice_type")]:
        if not s[key]:
            continue
        L.append(f"### {title}")
        L.append("")
        L.append("| 名称 | 数量 |")
        L.append("|------|------|")
        for name, cnt in s[key]:
            L.append(f"| {name} | {cnt} |")
        L.append("")

    L.append("## 三、中标金额分布")
    L.append("")
    L.append("| 金额区间 | 数量 | 占比 | 区间内金额合计(元) | 中位数(元) |")
    L.append("|----------|------|------|-------------------|-----------|")
    for d in s["amount_distribution"]:
        med = f"{d['median']:,.0f}" if d["median"] is not None else "-"
        L.append(f"| {d['bucket']} | {d['count']} | {d['ratio']:.1%} | "
                 f"{d['total_amount']:,.0f} | {med} |")
    L.append("")

    if s["by_year"]:
        L.append("## 四、时间分布")
        L.append("")
        L.append("| 年份 | 公告数 | 金额合计(元) |")
        L.append("|------|--------|--------------|")
        for y, cnt in s["by_year"]:
            L.append(f"| {y} | {cnt} | {s['amount_by_year'].get(y, 0):,.0f} |")
        L.append("")

    L.append("## 五、金额最大的项目")
    L.append("")
    top = sorted((b for b in bids if isinstance(b.get("amount"), (int, float))
                  and b["amount"] > 0),
                 key=lambda b: b["amount"], reverse=True)[:15]
    if top:
        L.append("| 项目 | 采购人 | 中标方 | 金额(元) | 类别 | 日期 |")
        L.append("|------|--------|--------|----------|------|------|")
        for b in top:
            L.append(f"| {str(b.get('project_name', ''))[:36]} | "
                     f"{str(b.get('buyer', ''))[:16]} | "
                     f"{str(b.get('winner', ''))[:20]} | "
                     f"{b['amount']:,.0f} | {b.get('category', '')} | "
                     f"{b.get('publish_date', '')} |")
        L.append("")

    L.append("---")
    L.append("")
    L.append("说明：金额为公告披露口径；节能收益分成、费率计价类项目无法折算为固定金额，"
             "金额字段留空并计入覆盖率分母之外。")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="分析 ESG 招投标数据")
    ap.add_argument("--input", nargs="+", default=["data/bids.json"])
    ap.add_argument("--config", default="config/sources.yaml")
    ap.add_argument("--output-dir", default="analysis")
    ap.add_argument("--since", default="", help="只看该日期之后的公告")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / args.config).read_text(encoding="utf-8")) or {}
    buckets = cfg.get("amount_buckets", [])

    paths = [Path(p) if Path(p).is_absolute() else ROOT / p for p in args.input]
    bids = load_bids(paths)
    if args.since:
        cutoff = date.fromisoformat(args.since)
        bids = [b for b in bids
                if (d := parse_date(b.get("publish_date", ""))) and d >= cutoff]
    if not bids:
        print("没有可分析的公告数据")
        return 1

    s = analyze(bids, buckets)

    out_dir = ROOT / args.output_dir if not Path(args.output_dir).is_absolute() else Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    dates = [parse_date(b.get("publish_date", "")) for b in bids]
    dates = [d for d in dates if d]
    period_note = (f"数据区间：{min(dates)} 至 {max(dates)}（{len(bids)} 条公告）"
                   if dates else f"共 {len(bids)} 条公告")

    (out_dir / "summary.md").write_text(render_markdown(s, bids, period_note), encoding="utf-8")
    (out_dir / "summary.json").write_text(
        json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"分析完成: {out_dir/'summary.md'}")
    print(f"  公告 {s['total_bids']} 条 ｜ 有金额 {s['with_amount']} 条 "
          f"({s['amount_coverage']:.0%}) ｜ 合计 {s['amount_sum']:,.0f} 元")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
