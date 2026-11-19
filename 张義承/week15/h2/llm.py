"""DeepSeek 客户端封装（走 OpenAI 兼容接口）。

环境变量：
    DEEPSEEK_API_KEY   必填，从环境读取
    DEEPSEEK_BASE_URL  默认 https://api.deepseek.com
    DEEPSEEK_MODEL     默认 deepseek-flash
"""

import os
from pathlib import Path

from openai import OpenAI

# 如果同目录下有 .env 就一并加载（没有也能跑，用系统环境变量）
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"


def base_url() -> str:
    return os.getenv("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL)


def model() -> str:
    return os.getenv("DEEPSEEK_MODEL", DEFAULT_MODEL)


def api_key() -> str:
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        raise RuntimeError("缺少环境变量 DEEPSEEK_API_KEY")
    return key


_client: OpenAI | None = None


def client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=api_key(), base_url=base_url(), timeout=60, max_retries=1)
    return _client


def chat(
    messages: list[dict],
    *,
    temperature: float = 0.7,
    json_mode: bool = False,
    max_tokens: int = 800,
) -> str:
    """单轮补全，返回纯文本。json_mode=True 时要求模型输出 JSON 对象。"""
    kwargs: dict = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = client().chat.completions.create(
        model=model(),
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        **kwargs,
    )
    return (resp.choices[0].message.content or "").strip()
