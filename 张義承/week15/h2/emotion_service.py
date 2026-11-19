"""进程1：情感识别服务（FastAPI，默认端口 8101）。

启动：
    python emotion_service.py
    # 或
    uvicorn emotion_service:app --port 8101

接口：
    POST /analyze  {"text": "..."}
      -> {"sentiment": "positive|negative|neutral", "emotion": "...",
          "confidence": 0.9, "reason": "...", "raw": "..."}
"""

import json
import os
import re

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import llm
from prompts import EMOTION_SYSTEM

PORT = 8101
VALID = ("positive", "negative", "neutral")

app = FastAPI(title="进程1 情感识别")


class AnalyzeRequest(BaseModel):
    text: str


def _parse_json(raw: str) -> dict:
    """模型偶尔会包一层 ```json ，这里做兜底解析。"""
    s = raw.strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.S).strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", s, flags=re.S)
        if not m:
            raise ValueError(f"无法解析模型输出：{raw[:200]}")
        return json.loads(m.group(0))


def normalize(data: dict) -> dict:
    sentiment = str(data.get("sentiment", "")).strip().lower()
    if sentiment not in VALID:
        sentiment = "neutral"
    try:
        confidence = float(data.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5
    return {
        "sentiment": sentiment,
        "emotion": str(data.get("emotion", "") or "平静"),
        "confidence": round(max(0.0, min(1.0, confidence)), 2),
        "reason": str(data.get("reason", "") or ""),
    }


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(400, "text 不能为空")

    raw = llm.chat(
        [
            {"role": "system", "content": EMOTION_SYSTEM},
            {"role": "user", "content": text},
        ],
        temperature=0.1,
        json_mode=True,
        max_tokens=300,
    )
    try:
        result = normalize(_parse_json(raw))
    except Exception as e:
        raise HTTPException(502, f"进程1 解析模型输出失败：{e}")

    result["raw"] = raw
    return result


@app.get("/health")
def health():
    return {"ok": True, "service": "进程1 情感识别", "port": PORT, "model": llm.model()}


if __name__ == "__main__":
    import uvicorn

    # 容器里必须绑 0.0.0.0，否则 Docker 端口映射到不了
    uvicorn.run(app, host=os.getenv("SERVICE_HOST", "0.0.0.0"), port=PORT)
