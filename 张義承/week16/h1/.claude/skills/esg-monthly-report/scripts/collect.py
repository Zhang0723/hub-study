#!/usr/bin/env python3
"""抓取候选网页并用 LLM 抽取结构化 ESG 事件。

输入 data/urls.jsonl，每行一条：
    {"url": "...", "title": "...", "source": "生态环境部", "section": "policy",
     "date_hint": "2026-11-25"}

输出 data/events.json：
    {"events": [{date, title, source, url, section, summary, key_facts[],
                 esg_dimensions[], significance, client_impact}], "failed": [...]}

用法：
    python collect.py --input data/urls.jsonl --output data/events.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_page import fetch  # noqa: E402
from llm import chat_json  # noqa: E402

SYSTEM = """你是资深 ESG 顾问，为客户（中国神华等能源/资源类企业）整理月度 ESG 动态。
你的任务是从给定网页正文中抽取结构化事实。要求：
1. 只依据正文写，不要编造。正文没提到的信息，字段留 null 或空数组。
2. 日期用 YYYY-MM-DD；正文有多个日期时取发布日期或正文标注的生效日期。
3. esg_dimensions 只从 E(环境)/S(社会)/G(治理) 中选，可多选，也可为空数组。
4. significance 从 high/medium/low 中选：high=强制性法规/评级变动/重大处罚，medium=行业规则/重要政策，low=一般动态。
5. client_impact 用 1-2 句说明对能源/资源类客户的具体影响，避免空话。
6. 全文用中文。"""

PROMPT = """请从下面的网页正文抽取 ESG 相关事件。

元信息：
- 标题：{title}
- 来源：{source}
- 板块：{section}
- 日期提示：{date_hint}

正文：
{doc}

严格按以下 JSON 结构输出：
{{
  "is_esg_related": true,
  "date": "YYYY-MM-DD",
  "title": "事件标题",
  "summary": "2-3 句概述这条动态讲了什么",
  "key_facts": ["关键事实1", "关键事实2"],
  "esg_dimensions": ["E"],
  "significance": "high",
  "client_impact": "对客户的具体影响",
  "entities": ["涉及的机构/公司/标准名称"]
}}

如果正文与 ESG / 可持续发展 / 碳排放 / 治理无关，把 is_esg_related 设为 false，date/title/summary 照填，其余留空。
JSON："""


def load_urls(path: Path) -> list[dict]:
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            print(f"跳过无法解析的行: {line[:80]}", file=sys.stderr)
            continue
        if obj.get("url"):
            items.append(obj)
    return items


def main() -> int:
    ap = argparse.ArgumentParser(description="抓取并抽取 ESG 事件")
    ap.add_argument("--input", default="data/urls.jsonl")
    ap.add_argument("--output", default="data/events.json")
    ap.add_argument("--client", default="中国神华")
    ap.add_argument("--min-chars", type=int, default=400)
    args = ap.parse_args()

    in_path, out_path = Path(args.input), Path(args.output)
    if not in_path.exists():
        print(f"找不到输入文件 {in_path}", file=sys.stderr)
        return 1

    candidates = load_urls(in_path)
    print(f"待处理 {len(candidates)} 条候选")

    events: list[dict] = []
    failed: list[dict] = []

    for i, cand in enumerate(candidates, 1):
        url = cand["url"]
        print(f"[{i}/{len(candidates)}] {cand.get('title', '')[:44]}", flush=True)

        page = fetch(url)
        if not page["ok"]:
            failed.append({"url": url, "reason": page.get("error", "抓取失败")})
            print(f"    抓取失败: {page.get('error')}")
            continue

        text = page["text"]
        if len(text) < args.min_chars:
            failed.append({"url": url, "reason": f"正文过短({len(text)}字)"})
            print(f"    正文过短，跳过")
            continue

        doc = text[:9000]
        try:
            rec = chat_json(
                PROMPT.format(
                    title=cand.get("title") or page["title"],
                    source=cand.get("source", ""),
                    section=cand.get("section", ""),
                    date_hint=cand.get("date_hint", ""),
                    doc=doc,
                ),
                system=SYSTEM,
                temperature=0.2,
                max_tokens=1200,
            )
        except Exception as exc:  # noqa: BLE001
            failed.append({"url": url, "reason": f"LLM 抽取失败: {exc}"})
            print(f"    LLM 失败: {exc}")
            continue

        if not isinstance(rec, dict) or not rec.get("is_esg_related"):
            print("    非 ESG 相关，跳过")
            continue

        rec.update({
            "url": url,
            "source": cand.get("source", ""),
            "section": cand.get("section", ""),
        })
        events.append(rec)
        print(f"    OK  {rec.get('date')} [{rec.get('significance')}] {str(rec.get('title'))[:40]}")
        time.sleep(0.5)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({"events": events, "failed": failed}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n抽取 {len(events)} 条 ESG 事件，失败 {len(failed)} 条 -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
