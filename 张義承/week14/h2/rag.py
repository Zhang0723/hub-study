"""文本切块、检索、多模态问答。

检索用轻量 BM25（jieba 分词，装了就自动用），不依赖向量库，作业够用。
问答走 DeepSeek 的 OpenAI 兼容接口；用户传图时按 OpenAI 的 image_url 格式
一起送进去（模型不支持图片会自动降级成纯文本再问一次）。
"""

import json
import math
import os
import re
from collections import Counter
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PARSED_DIR = BASE_DIR / "data" / "parsed"

IMG_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


# ------------------------------------------------------------------
# 分词
# ------------------------------------------------------------------
try:
    import jieba

    jieba.setLogLevel(60)  # 关掉加载词典的日志

    def tokenize(text: str) -> list[str]:
        return [w for w in jieba.cut(text) if w.strip()]
except ImportError:  # 没装 jieba 也能跑：英文按词，中文按字 + 二元组

    def tokenize(text: str) -> list[str]:
        words = re.findall(r"[a-zA-Z0-9_]+", text.lower())
        cjk = re.findall(r"[一-鿿]", text)
        bigrams = [cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1)]
        return words + cjk + bigrams


# ------------------------------------------------------------------
# 切块：解析完成后由 worker 调用
# ------------------------------------------------------------------
def build_chunks(markdown: str, doc_id: str, filename: str) -> list[dict]:
    """按标题 + 长度切块，块内保留图片 markdown，后面回答可以直接引用。"""
    chunks: list[dict] = []
    buf: list[str] = []
    heading = ""

    def flush() -> None:
        nonlocal buf
        text = "\n".join(buf).strip()
        buf = []
        if not text:
            return
        chunks.append(
            {
                "chunk_id": f"{doc_id}-{len(chunks)}",
                "doc_id": doc_id,
                "filename": filename,
                "heading": heading,
                "text": text,
                "images": IMG_RE.findall(text),
            }
        )

    for line in markdown.splitlines():
        if line.startswith("#"):
            flush()
            heading = line.lstrip("# ").strip()
            buf.append(line)
        else:
            buf.append(line)
            if len("\n".join(buf)) > 700:
                flush()
    flush()
    return chunks


# ------------------------------------------------------------------
# 检索（BM25 简化版）
# ------------------------------------------------------------------
def load_all_chunks() -> list[dict]:
    chunks: list[dict] = []
    if not PARSED_DIR.exists():
        return chunks
    for f in sorted(PARSED_DIR.glob("*/chunks.json")):
        try:
            chunks.extend(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    return chunks


def search(question: str, top_k: int = 4) -> list[dict]:
    chunks = load_all_chunks()
    if not chunks:
        return []

    q_tokens = Counter(tokenize(question))
    docs_tokens = [Counter(tokenize(c["text"] + " " + c.get("heading", ""))) for c in chunks]

    n = len(chunks)
    df: Counter = Counter()
    for dt in docs_tokens:
        for t in q_tokens:
            if dt.get(t):
                df[t] += 1

    scored = []
    for chunk, dt in zip(chunks, docs_tokens):
        score = 0.0
        for t, qf in q_tokens.items():
            tf = dt.get(t, 0)
            if not tf:
                continue
            idf = math.log(1 + n / (1 + df[t]))
            score += qf * idf * tf / (tf + 1.5)
        if score > 0:
            scored.append((score, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:top_k]]


# ------------------------------------------------------------------
# 问答
# ------------------------------------------------------------------
SYSTEM_PROMPT = """你是一个文档问答助手。请严格依据「参考资料」回答问题：
1. 用中文回答，输出 Markdown，可以分点、加粗、用表格。
2. 如果参考资料里有配图，且与问题相关，请在回答中直接插入图片，格式为 ![描述](/files/parsed/...)，
   实现图文混排。只能引用参考资料里出现过的图片路径，不要自己编造。
3. 参考资料不足以回答时，明确说「资料中没有找到」，不要编造内容。
4. 如果用户同时提供了图片，请结合图片内容一起回答。"""


def _client():
    from openai import OpenAI

    return OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )


def _model() -> str:
    return os.getenv("DEEPSEEK_MODEL", "deepseek-flash")


def _build_prompt(question: str, chunks: list[dict]) -> str:
    if not chunks:
        context = "（当前没有已解析完成的文档）"
    else:
        parts = []
        for i, c in enumerate(chunks, 1):
            part = f"[{i}] 来源：{c['filename']}\n{c['text']}"
            if c.get("images"):
                part += "\n可用配图：" + "、".join(c["images"][:4])
            parts.append(part)
        context = "\n\n".join(parts)

    return f"参考资料：\n{context}\n\n用户问题：{question}"


def answer(question: str, image_data_url: str | None = None, top_k: int = 4) -> dict:
    chunks = search(question, top_k)
    prompt = _build_prompt(question, chunks)

    if image_data_url:
        content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": image_data_url}},
        ]
    else:
        content = prompt

    client = _client()
    model = _model()

    notes = []
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            temperature=0.3,
        )
    except Exception as e:
        if not image_data_url:
            raise
        # 模型不支持图片输入时降级：只发文本
        notes.append(f"模型不支持图片输入，已降级为纯文本问答（{type(e).__name__}）")
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt + "\n\n（用户还上传了一张图片，但当前模型无法识别）"},
            ],
            temperature=0.3,
        )

    return {
        "answer": resp.choices[0].message.content or "",
        "sources": [
            {
                "filename": c["filename"],
                "doc_id": c["doc_id"],
                "heading": c.get("heading", ""),
                "snippet": c["text"][:160],
            }
            for c in chunks
        ],
        "images": [img for c in chunks for img in c.get("images", [])][:6],
        "model": model,
        "notes": notes,
    }
