"""后端进程：接受前端输入，串联「进程1」和「进程2」。

两种编排实现：
    framework=langgraph      → langgraph_flow.run(text)
    framework=openai-agents  → agents_flow.run(text)
默认值由环境变量 FRAMEWORK 指定（未设置则 langgraph）。

启动（先启动 emotion_service.py 和 respond_service.py）：
    python backend.py            # http://127.0.0.1:8000
    # 或
    uvicorn backend:app --port 8000
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
FRAMEWORKS = ("langgraph", "openai-agents")
DEFAULT_FRAMEWORK = os.getenv("FRAMEWORK", "langgraph")

if DEFAULT_FRAMEWORK not in FRAMEWORKS:
    DEFAULT_FRAMEWORK = "langgraph"

app = FastAPI(title="情感陪伴后端")
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class ChatRequest(BaseModel):
    text: str
    framework: str | None = None


def run_pipeline(text: str, framework: str) -> dict:
    if framework == "openai-agents":
        import agents_flow

        return agents_flow.run(text)
    import langgraph_flow

    return langgraph_flow.run(text)


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/chat")
def chat(req: ChatRequest):
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(400, "输入不能为空")

    framework = req.framework or DEFAULT_FRAMEWORK
    if framework not in FRAMEWORKS:
        raise HTTPException(400, f"framework 只能是 {FRAMEWORKS}")

    try:
        return run_pipeline(text, framework)
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

    uvicorn.run(app, host="127.0.0.1", port=PORT)
