"""多模态 RAG 问答 —— Web 前后端（FastAPI）

流程：
    浏览器上传 PDF → 存盘并写 pending 状态 → 发 Kafka 消息
    worker.py 消费消息 → MinerU 解析 → 落盘 → 状态改 done
    浏览器轮询 /api/docs 显示「待解析 / 解析中 / 解析完成」
    提问（可带图）→ 检索 chunk → DeepSeek 回答（图文混排 markdown）

启动：
    export DEEPSEEK_API_KEY=sk-xxxxxxxx
    python worker.py                      # 终端 1：解析 worker
    uvicorn app:app --port 8000           # 终端 2：Web 服务
    浏览器打开 http://127.0.0.1:8000
"""

import json
import os
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from kafka import KafkaProducer
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent
# 必须先加载 .env，再 import rag（rag 在函数内读环境变量，这里额外保险）
load_dotenv(BASE_DIR / ".env")

import rag  # noqa: E402

DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
PARSED_DIR = DATA_DIR / "parsed"
STATUS_DIR = DATA_DIR / "status"
STATIC_DIR = BASE_DIR / "static"

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
TOPIC = os.getenv("PDF_TOPIC", "pdf-parse")
MAX_FILE_MB = int(os.getenv("MAX_FILE_MB", "50"))

for d in (UPLOAD_DIR, PARSED_DIR, STATUS_DIR):
    d.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="多模态 RAG 问答")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/files", StaticFiles(directory=DATA_DIR), name="files")

_producer: KafkaProducer | None = None


# ------------------------------------------------------------------
# 状态文件
# ------------------------------------------------------------------
def write_status(doc_id: str, **fields) -> None:
    path = STATUS_DIR / f"{doc_id}.json"
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data.update(fields, updated_at=time.strftime("%Y-%m-%d %H:%M:%S"))
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def read_all_status() -> list[dict]:
    docs = []
    for f in STATUS_DIR.glob("*.json"):
        try:
            docs.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    docs.sort(key=lambda d: d.get("created_at", ""), reverse=True)
    return docs


# ------------------------------------------------------------------
# Kafka
# ------------------------------------------------------------------
def get_producer() -> KafkaProducer:
    global _producer
    if _producer is None:
        _producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
            key_serializer=lambda k: k.encode("utf-8") if k else None,
            request_timeout_ms=5000,
        )
    return _producer


# ------------------------------------------------------------------
# 接口
# ------------------------------------------------------------------
class ChatRequest(BaseModel):
    question: str
    image: str | None = None  # data:image/png;base64,...


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...)):
    """一次可上传多个 PDF：存盘 → 写状态 → 发 Kafka。"""
    try:
        producer = get_producer()
    except Exception as e:
        raise HTTPException(503, f"Kafka 连接失败（{type(e).__name__}: {e}），请先启动 Kafka")

    accepted, rejected = [], []
    for f in files:
        name = f.filename or "unnamed.pdf"
        if not name.lower().endswith(".pdf"):
            rejected.append({"filename": name, "reason": "只支持 PDF"})
            continue

        content = await f.read()
        if len(content) > MAX_FILE_MB * 1024 * 1024:
            rejected.append({"filename": name, "reason": f"超过 {MAX_FILE_MB}MB"})
            continue

        doc_id = uuid.uuid4().hex[:12]
        dest = UPLOAD_DIR / f"{doc_id}.pdf"
        dest.write_bytes(content)

        created = time.strftime("%Y-%m-%d %H:%M:%S")
        write_status(
            doc_id,
            filename=name,
            size=len(content),
            status="pending",
            message="待解析",
            created_at=created,
        )

        try:
            producer.send(
                TOPIC,
                key=doc_id,
                value={"doc_id": doc_id, "filename": name, "path": str(dest)},
            )
            producer.flush(timeout=10)
        except Exception as e:
            write_status(doc_id, status="error", message=f"任务投递失败：{type(e).__name__}: {e}")
            rejected.append({"filename": name, "reason": f"投递 Kafka 失败：{e}"})
            continue

        accepted.append({"doc_id": doc_id, "filename": name, "status": "pending"})

    return {"accepted": accepted, "rejected": rejected}


@app.get("/api/docs")
def docs():
    """前端轮询：所有文档状态 + 汇总计数。"""
    items = read_all_status()
    summary = {"pending": 0, "parsing": 0, "done": 0, "error": 0}
    for d in items:
        s = d.get("status", "pending")
        summary[s] = summary.get(s, 0) + 1
    return {"docs": items, "summary": summary}


@app.post("/api/chat")
def chat(req: ChatRequest):
    question = (req.question or "").strip()
    if not question:
        raise HTTPException(400, "问题不能为空")
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise HTTPException(500, "未配置 DEEPSEEK_API_KEY（写在 h2/.env 里或启动前 export）")

    try:
        result = rag.answer(question, image_data_url=req.image)
    except Exception as e:
        raise HTTPException(500, f"问答失败：{type(e).__name__}: {e}")
    return result


@app.get("/api/health")
def health():
    kafka_ok = True
    try:
        get_producer()
    except Exception:
        kafka_ok = False
    return {
        "ok": True,
        "kafka": kafka_ok,
        "kafka_bootstrap": KAFKA_BOOTSTRAP,
        "topic": TOPIC,
        "model": rag._model(),
        "api_key_set": bool(os.getenv("DEEPSEEK_API_KEY")),
        "mineru": bool(__import__("shutil").which("mineru") or __import__("shutil").which("magic-pdf")),
    }
