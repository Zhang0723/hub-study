"""进程2：回应生成服务（FastAPI，默认端口 8102）。

拿到进程1 的情感结论后：
    正向 → 鼓励（encourage）
    负面 → 排解（comfort）
    其它 → 陪伴（neutral）

启动：
    python respond_service.py
    # 或
    uvicorn respond_service:app --port 8102

接口：
    POST /respond {"text": "...", "sentiment": "negative", "emotion": "焦虑", "mode": "comfort"}
      -> {"reply": "...", "mode": "comfort"}
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import llm
from prompts import MODE_TITLES, respond_system

PORT = 8102
VALID_MODES = ("encourage", "comfort", "neutral")

app = FastAPI(title="进程2 鼓励/排解")


class RespondRequest(BaseModel):
    text: str
    sentiment: str = "neutral"
    emotion: str = ""
    mode: str | None = None  # 不传则按 sentiment 推导


def resolve_mode(mode: str | None, sentiment: str) -> str:
    if mode in VALID_MODES:
        return mode
    return {"positive": "encourage", "negative": "comfort"}.get(sentiment, "neutral")


@app.post("/respond")
def respond(req: RespondRequest):
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(400, "text 不能为空")

    sentiment = (req.sentiment or "neutral").strip().lower()
    mode = resolve_mode(req.mode, sentiment)

    user_prompt = f"""用户的情绪识别结果：{sentiment}（{req.emotion or '未知'}）
用户原话：
{text}

请以「{MODE_TITLES[mode]}」的方式回应。"""

    reply = llm.chat(
        [
            {"role": "system", "content": respond_system(mode)},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.8,
        max_tokens=500,
    )
    if not reply:
        raise HTTPException(502, "进程2 模型返回为空")
    return {"reply": reply, "mode": mode}


@app.get("/health")
def health():
    return {"ok": True, "service": "进程2 鼓励/排解", "port": PORT, "model": llm.model()}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PORT)
