"""PDF 解析 worker：从 Kafka 拿任务，解析后落盘，并更新状态。

启动：
    python worker.py

解析优先用 MinerU 命令行（mineru / magic-pdf），没有装就降级用 PyMuPDF
（只能抽文本和内嵌图片，不做版面分析，作业演示足够）。
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

from kafka import KafkaConsumer

import rag

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
PARSED_DIR = DATA_DIR / "parsed"
STATUS_DIR = DATA_DIR / "status"

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
TOPIC = os.getenv("PDF_TOPIC", "pdf-parse")
GROUP_ID = os.getenv("PDF_GROUP", "pdf-parser")
PARSE_TIMEOUT = int(os.getenv("PARSE_TIMEOUT", "600"))


# ------------------------------------------------------------------
# 状态读写（和 app.py 共用同一套文件格式）
# ------------------------------------------------------------------
def write_status(doc_id: str, **fields) -> None:
    STATUS_DIR.mkdir(parents=True, exist_ok=True)
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


# ------------------------------------------------------------------
# MinerU
# ------------------------------------------------------------------
def _find_mineru() -> str | None:
    for name in ("mineru", "magic-pdf"):
        exe = shutil.which(name)
        if exe:
            return exe
    return None


def parse_with_mineru(pdf: Path, out_dir: Path) -> Path:
    """调用 MinerU 解析，返回生成的 markdown 路径。"""
    exe = _find_mineru()
    assert exe
    cmd = [exe, "-p", str(pdf), "-o", str(out_dir)]
    print(f"[worker] 执行：{' '.join(cmd)}")
    subprocess.run(cmd, check=True, timeout=PARSE_TIMEOUT,
                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    mds = sorted(out_dir.rglob("*.md"), key=lambda p: p.stat().st_size, reverse=True)
    if not mds:
        raise RuntimeError("MinerU 没有产出 markdown")
    return mds[0]


# ------------------------------------------------------------------
# 降级：PyMuPDF
# ------------------------------------------------------------------
def parse_with_pymupdf(pdf: Path, out_dir: Path) -> Path:
    try:
        import pymupdf as fitz  # PyMuPDF 2.x
    except ImportError:
        import fitz  # 老版本

    images_dir = out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(pdf)
    parts = [f"# {pdf.stem}\n"]
    for page_no, page in enumerate(doc, 1):
        parts.append(f"\n## 第 {page_no} 页\n")
        text = page.get_text().strip()
        if text:
            parts.append(text + "\n")

        for idx, info in enumerate(page.get_images(full=True), 1):
            xref = info[0]
            try:
                pix = fitz.Pixmap(doc, xref)
                if pix.n - pix.alpha >= 4:  # CMYK 转 RGB
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                name = f"page{page_no}_img{idx}.png"
                pix.save(str(images_dir / name))
                parts.append(f"![](images/{name})\n")
            except Exception:
                continue
    doc.close()

    md_path = out_dir / "content.md"
    md_path.write_text("\n".join(parts), encoding="utf-8")
    return md_path


# ------------------------------------------------------------------
# 解析 + 保存
# ------------------------------------------------------------------
IMG_LINK_RE = re.compile(r"(!\[[^\]]*\]\()([^)]+)(\))")


def _rewrite_image_links(markdown: str, md_dir: Path, doc_id: str) -> str:
    """把图片相对路径改成 /files/parsed/{doc_id}/...，前端才能直接渲染。

    md_dir 是原始 markdown 所在目录；其内容已被原样复制到
    data/parsed/{doc_id}/，所以相对路径可以平移过去。
    """

    def repl(m: re.Match) -> str:
        alt_prefix, src, tail = m.group(1), m.group(2), m.group(3)
        if src.startswith(("http://", "https://", "/files/")):
            return m.group(0)
        target = (md_dir / src).resolve()
        try:
            rel = target.relative_to(md_dir.resolve())
        except ValueError:
            return m.group(0)
        # 图片没被复制过来就不改写，避免前端出现死链
        if not (PARSED_DIR / doc_id / rel).exists():
            return m.group(0)
        return f"{alt_prefix}/files/parsed/{doc_id}/{rel.as_posix()}{tail}"

    return IMG_LINK_RE.sub(repl, markdown)


def parse_document(pdf: Path, doc_id: str, filename: str) -> dict:
    out_root = PARSED_DIR / doc_id
    out_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        try:
            md_path = parse_with_mineru(pdf, tmp_dir)
            parser = "mineru"
        except Exception as e:
            print(f"[worker] MinerU 不可用（{e}），降级 PyMuPDF")
            md_path = parse_with_pymupdf(pdf, tmp_dir)
            parser = "pymupdf"

        # 把 markdown 和它同级的图片目录一起搬过来
        src_dir = md_path.parent
        for item in src_dir.iterdir():
            if item.is_file() and item.suffix.lower() in {".json", ".txt"} and item.name != "content.md":
                continue  # 跳过 MinerU 的中间产物
            dest = out_root / item.name
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            elif item.name != md_path.name:
                shutil.copy2(item, dest)

        markdown = md_path.read_text(encoding="utf-8", errors="ignore")
        markdown = _rewrite_image_links(markdown, src_dir, doc_id)
        (out_root / "content.md").write_text(markdown, encoding="utf-8")

    chunks = rag.build_chunks(markdown, doc_id, filename)
    (out_root / "chunks.json").write_text(
        json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    images = [p for p in out_root.rglob("*")
              if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}]

    return {
        "parser": parser,
        "chars": len(markdown),
        "chunks": len(chunks),
        "images": len(images),
    }


# ------------------------------------------------------------------
# 主循环
# ------------------------------------------------------------------
def handle(job: dict) -> None:
    doc_id = job["doc_id"]
    pdf = Path(job["path"])
    filename = job.get("filename", pdf.name)

    write_status(doc_id, status="parsing", message="正在解析")
    print(f"[worker] 开始解析 {filename} ({doc_id})")

    try:
        if not pdf.exists():
            raise FileNotFoundError(f"文件不存在：{pdf}")
        info = parse_document(pdf, doc_id, filename)
        write_status(doc_id, status="done", message="解析完成", **info)
        print(f"[worker] 完成 {filename}: {info}")
    except Exception as e:
        traceback.print_exc()
        write_status(doc_id, status="error", message=f"解析失败：{type(e).__name__}: {e}")
        print(f"[worker] 失败 {filename}: {e}")


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PARSED_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[worker] 连接 Kafka {KAFKA_BOOTSTRAP} / topic={TOPIC} / group={GROUP_ID}")
    consumer = KafkaConsumer(
        TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id=GROUP_ID,
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
    )
    print("[worker] 已启动，等待任务…")

    try:
        for message in consumer:
            try:
                handle(message.value)
            except Exception:
                traceback.print_exc()
    except KeyboardInterrupt:
        print("\n[worker] 退出")
    finally:
        consumer.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
