#!/usr/bin/env python3
"""配置加载与工具函数。"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml


def load_config(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"找不到配置文件 {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def match_keywords(title: str, cfg: dict) -> bool:
    """标题是否命中 ESG 关键词。命中 'must' 任一，或同时命中 'any' 中两个以上则算命中。

    单纯一个"碳"字噪声太大（比如"碳素钢管"），所以要求 any 类关键词至少两个，
    或者命中 must 类（更具体的多字词）。
    """
    kws = cfg.get("keywords", {})
    must = kws.get("must", [])
    any_ = kws.get("any", [])
    exclude = kws.get("exclude", [])

    if any(e in title for e in exclude):
        return False
    if any(m in title for m in must):
        return True
    return sum(1 for a in any_ if a in title) >= kws.get("any_min_hits", 2)


def load_seen(path: Path) -> set[str]:
    """读取已入库 URL 集合。"""
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    return set(data.get("urls", []))


def save_seen(path: Path, urls: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"urls": sorted(urls)}, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def normalize_amount(amount) -> float | None:
    """把 '251.6万元' / '2,516,000元' / 2516000 统一成元。"""
    if amount is None:
        return None
    if isinstance(amount, (int, float)):
        return float(amount)
    s = str(amount).replace(",", "").strip()
    m = re.search(r"([\d.]+)\s*(亿|万)?\s*元?", s)
    if not m:
        return None
    try:
        val = float(m.group(1))
    except ValueError:
        return None
    unit = m.group(2)
    if unit == "亿":
        val *= 1e8
    elif unit == "万":
        val *= 1e4
    return val
