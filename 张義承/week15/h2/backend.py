"""后端进程：接受前端输入，串联「进程1」和「进程2」。

本目录是 **openai-agents 版本**：编排固定走 agents_flow.run(text)。
（langgraph 版本在 ../h1 里。）

启动（先启动 emotion_service.py 和 respond_service.py）：
    python backend.py            # http://127.0.0.1:8000
    # 或
    uvicorn backend:app --port 8000
    # 容器里走 run_all.py，三个进程一起起
"""

import os
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import service_client as svc

PORT = 8000
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
FRAMEWORKS = ("openai-agents",)
DEFAULT_FRAMEWORK = "openai-agents"

app = FastAPI(title="情感陪伴后端")
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ChatRequest(BaseModel):
    text: str
    framework: str | None = None


def run_pipeline(text: str) -> dict:
    import agents_flow

    return agents_flow.run(text)


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/chat")
def chat(req: ChatRequest):
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(400, "输入不能为空")

    try:
        result = run_pipeline(text)
        result["framework"] = DEFAULT_FRAMEWORK
        return result
    except httpx.ConnectError:
        raise HTTPException(
            503,
            "连不上进程1/进程2，请先启动：python emotion_service.py 和 python respond_service.py",
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"子进程返回错误：{e.response.text[:300]}")
    except Exception as e:
        raise HTTPException(500, f"编排失败：{type(e).__name__}: {e}")


@app.get("/api/health")
def health():
    def probe(url: str) -> dict:
        try:
            r = httpx.get(f"{url}/health", timeout=5)
            return r.json()
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    return {
        "ok": True,
        "default_framework": DEFAULT_FRAMEWORK,
        "frameworks": list(FRAMEWORKS),
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
        "api_key_set": bool(os.getenv("DEEPSEEK_API_KEY")),
        "process1_emotion": probe(svc.EMOTION_URL),
        "process2_respond": probe(svc.RESPOND_URL),
    }


if __name__ == "__main__":
    import uvicorn

    # 容器里必须绑 0.0.0.0，否则 Docker 端口映射到不了
    uvicorn.run(app, host=os.getenv("SERVICE_HOST", "0.0.0.0"), port=PORT)
