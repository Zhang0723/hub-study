#!/usr/bin/env python3
"""LLM 客户端（DeepSeek / OpenAI 兼容接口）。

环境变量：
    DEEPSEEK_API_KEY   必填
    DEEPSEEK_BASE_URL  默认 https://api.deepseek.com
    DEEPSEEK_MODEL     默认 deepseek-chat
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from openai import OpenAI

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent.parent.parent / ".env")
except ImportError:
    pass

_client: OpenAI | None = None


def api_key() -> str:
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("缺少环境变量 DEEPSEEK_API_KEY")
    return key


def client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=api_key(),
            base_url=os.getenv("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL),
            timeout=120,
            max_retries=2,
        )
    return _client


def chat(
    messages: list[dict],
    *,
    temperature: float = 0.3,
    json_mode: bool = False,
    max_tokens: int = 2000,
) -> str:
    """单轮补全，返回纯文本。json_mode=True 时模型被要求输出 JSON。"""
    kwargs: dict = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = client().chat.completions.create(
        model=os.getenv("DEEPSEEK_MODEL", DEFAULT_MODEL),
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        **kwargs,
    )
    return resp.choices[0].message.content or ""


def chat_json(
    prompt: str,
    *,
    system: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 2000,
) -> dict | list:
    """要求模型返回 JSON 并解析。解析失败时从文本里抠出 JSON 片段再试。"""
    msgs = ([{"role": "system", "content": system}] if system else []) + [
        {"role": "user", "content": prompt}
    ]
    text = chat(msgs, temperature=temperature, json_mode=True, max_tokens=max_tokens)
    return parse_json(text)


def parse_json(text: str) -> dict | list:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for pattern in (r"\{.*\}", r"\[.*\]"):
        m = re.search(pattern, text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                continue
    raise ValueError(f"无法解析 JSON: {text[:200]}")
