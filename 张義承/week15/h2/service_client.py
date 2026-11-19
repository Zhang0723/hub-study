"""访问「进程1」「进程2」两个服务的 HTTP 客户端。

进程1（情感识别）: POST http://127.0.0.1:8101/analyze
进程2（鼓励/排解）: POST http://127.0.0.1:8102/respond

langgraph 和 openai-agents 两套编排都通过这里跨进程调用。
"""

import os

import httpx

EMOTION_URL = os.getenv("EMOTION_URL", "http://127.0.0.1:8101")
RESPOND_URL = os.getenv("RESPOND_URL", "http://127.0.0.1:8102")
TIMEOUT = float(os.getenv("SERVICE_TIMEOUT", "90"))


def analyze_emotion(text: str) -> dict:
    """调用进程1：返回 {sentiment, emotion, confidence, reason}。"""
    with httpx.Client(timeout=TIMEOUT) as c:
        r = c.post(f"{EMOTION_URL}/analyze", json={"text": text})
        r.raise_for_status()
        return r.json()


def generate_reply(text: str, sentiment: str, emotion: str = "", mode: str = "neutral") -> str:
    """调用进程2：返回回应文本。mode ∈ encourage / comfort / neutral。"""
    with httpx.Client(timeout=TIMEOUT) as c:
        r = c.post(
            f"{RESPOND_URL}/respond",
            json={"text": text, "sentiment": sentiment, "emotion": emotion, "mode": mode},
        )
        r.raise_for_status()
        return r.json()["reply"]


def pick_mode(sentiment: str) -> str:
    """把情感结论映射成进程2 的回应模式：正向→鼓励，负面→排解，其余→陪伴。"""
    return {"positive": "encourage", "negative": "comfort"}.get(sentiment, "neutral")
