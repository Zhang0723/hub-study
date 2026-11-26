#!/usr/bin/env python3
"""把抽取到的 ESG 事件组装成月度报告（Markdown）。

输入 data/events.json + config/clients.yaml
输出 output/esg-monthly-report-<client>-<period>.md

用法：
    python build_report.py --client shenhua --events data/events.json
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

SECTION_TITLES = {
    "policy": "一、ESG 政策、评级与标准动态",
    "rating": "一、ESG 政策、评级与标准动态",
    "standard": "一、ESG 政策、评级与标准动态",
    "industry": "二、所属行业新闻动态与最佳实践",
    "company": "三、客户公司动态与 ESG 建议",
    "peer": "四、对标企业 ESG 关键行动",
}
SIG_LABEL = {"high": "🔴 高", "medium": "🟡 中", "low": "⚪ 低"}
SIG_ORDER = {"high": 0, "medium": 1, "low": 2}


def load_events(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("events", [])


def group_by_section(events: list[dict]) -> dict[str, list[dict]]:
    """按板块分组；组内先按重要性（高->低），同重要性内按日期倒序。"""
    groups: dict[str, list[dict]] = defaultdict(list)
    for ev in events:
        groups[ev.get("section") or "policy"].append(ev)
    for lst in groups.values():
        lst.sort(key=lambda e: e.get("date") or "", reverse=True)
        lst.sort(key=lambda e: SIG_ORDER.get(e.get("significance", "low"), 3))
    return groups


def render_event(ev: dict) -> str:
    dims = "/".join(ev.get("esg_dimensions") or []) or "-"
    sig = SIG_LABEL.get(ev.get("significance", "low"), "⚪ 低")
    lines = [
        f"**{ev.get('date', '日期未知')}｜{ev.get('title', '无标题')}**",
        "",
        f"- 来源：{ev.get('source', '-')} ｜ 板块：{dims} ｜ 重要性：{sig}",
        f"- 摘要：{ev.get('summary', '-')}",
    ]
    for fact in ev.get("key_facts") or []:
        lines.append(f"- 关键事实：{fact}")
    if ev.get("client_impact"):
        lines.append(f"- 对客户的影响：{ev['client_impact']}")
    if ev.get("entities"):
        lines.append(f"- 涉及主体：{'、'.join(ev['entities'])}")
    lines.append(f"- 来源链接：{ev.get('url', '-')}")
    lines.append("")
    return "\n".join(lines)


def render_section(title: str, events: list[dict]) -> str:
    if not events:
        return f"### {title}\n\n本期未采集到该板块的有效动态。\n"
    parts = [f"### {title}\n"]
    for ev in events:
        parts.append(render_event(ev))
    return "\n".join(parts)


def build_summary(events: list[dict], client: dict, period: str) -> str:
    sig = defaultdict(int)
    for ev in events:
        sig[ev.get("significance", "low")] += 1
    dims = defaultdict(int)
    for ev in events:
        for d in ev.get("esg_dimensions") or []:
            dims[d] += 1

    top = sorted(events, key=lambda e: SIG_ORDER.get(e.get("significance", "low"), 3))[:3]
    bullets = []
    for ev in top:
        bullets.append(f"- **{ev.get('significance', 'low')}**｜{ev.get('title', '')}"
                       f"（{ev.get('date', '')}，{ev.get('source', '')}）")
    if not bullets:
        bullets.append("- 本期无重点事件")

    dim_text = "、".join(f"{k}({v})" for k, v in sorted(dims.items(), key=lambda x: -x[1])) or "无"
    return "\n".join([
        "## 本期摘要",
        "",
        f"- 报告客户：{client['full_name']}（{client['sector']}）",
        f"- 报告周期：{period}",
        f"- 采集动态：{len(events)} 条 ｜ 高 {sig.get('high', 0)} / 中 {sig.get('medium', 0)} / 低 {sig.get('low', 0)}",
        f"- 议题分布：{dim_text}",
        "",
        "### 本期最需关注",
        "",
        *bullets,
        "",
    ])


def build_recommendations(events: list[dict], client: dict) -> str:
    """按焦点议题，从事件里派生建议。"""
    topics = client.get("focus_topics") or []
    hits: dict[str, list[dict]] = defaultdict(list)
    for ev in events:
        blob = " ".join(str(ev.get(k, "")) for k in ("title", "summary", "client_impact"))
        blob += " " + " ".join(ev.get("key_facts") or [])
        for t in topics:
            head = t[:2]
            if head and head in blob:
                hits[t].append(ev)

    lines = ["### 建议动作\n"]
    if not hits:
        lines.append("- 本期动态未直接触及既有重点议题，维持既有披露节奏即可。\n")
        return "\n".join(lines)

    for topic, evs in hits.items():
        best = min(evs, key=lambda e: SIG_ORDER.get(e.get("significance", "low"), 3))
        lines.append(f"- **{topic}**：结合「{best.get('title', '')}」"
                     f"（{best.get('date', '')}），建议核对本季度披露口径是否需要同步更新。")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 ESG 月报")
    ap.add_argument("--client", default="shenhua")
    ap.add_argument("--events", default="data/events.json")
    ap.add_argument("--period", default="", help="YYYY-MM，留空按上月")
    ap.add_argument("--output-dir", default="output")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config" / "clients.yaml").read_text(encoding="utf-8"))
    clients = cfg.get("clients", {})
    if args.client not in clients:
        print(f"未知客户 {args.client}，可选：{list(clients)}")
        return 1
    client = clients[args.client]

    events_path = ROOT / args.events if not Path(args.events).is_absolute() else Path(args.events)
    if not events_path.exists():
        print(f"找不到事件文件 {events_path}")
        return 1
    events = load_events(events_path)

    today = date.today()
    period = args.period or f"{today.year - (1 if today.month == 1 else 0)}-{(today.month - 2) % 12 + 1:02d}"
    groups = group_by_section(events)

    out_dir = ROOT / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"esg-monthly-report-{args.client}-{period}.md"

    body = [
        f"# {client['full_name']} ESG 月报（{period}）",
        "",
        build_summary(events, client, period),
        "---",
        "",
    ]

    order = ["policy", "industry", "company", "peer"]
    seen_titles = set()
    for sec in order:
        evs = groups.get(sec) or []
        if sec == "policy":
            evs = (groups.get("policy", []) + groups.get("rating", [])
                   + groups.get("standard", []))
            evs.sort(key=lambda e: e.get("date") or "", reverse=True)
            evs.sort(key=lambda e: SIG_ORDER.get(e.get("significance", "low"), 3))
        title = SECTION_TITLES.get(sec, sec)
        body.append(render_section(title, evs))
        body.append("---")
        body.append("")

    body.append("## 五、面向客户的建议")
    body.append("")
    body.append(build_recommendations(events, client))
    body.append("---")
    body.append("")
    body.append("## 附：数据说明")
    body.append("")
    body.append(f"- 采集范围：政策/评级/标准、行业动态、客户公司动态、对标企业动态五个板块")
    body.append(f"- 有效事件：{len(events)} 条 ｜ 重要性分布：高 "
                f"{sum(1 for e in events if e.get('significance') == 'high')} / 中 "
                f"{sum(1 for e in events if e.get('significance') == 'medium')} / 低 "
                f"{sum(1 for e in events if e.get('significance') == 'low')}")
    body.append("- 本报告由 ESG 月报 skill 自动生成，事实性内容均标注来源链接；")
    body.append("  影响判断与建议为模型辅助输出，落地前请人工复核。")
    body.append("")

    out_path.write_text("\n".join(body), encoding="utf-8")
    print(f"报告已生成: {out_path}  ({len(events)} 条事件)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
