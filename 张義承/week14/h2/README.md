# 多模态 RAG 问答（Kafka 版）

浏览器上传 PDF → Kafka 投递任务 → 解析 worker 用 MinerU 解析 → 落盘 → 检索问答。

```
浏览器 ──POST /api/upload──► FastAPI ──Kafka: pdf-parse──► worker.py
   ▲                            │                              │
   │                            │                        MinerU / PyMuPDF
   └──GET /api/docs 轮询状态────┘                              │
   │                                                           ▼
   └──POST /api/chat──► 检索 chunks ──► DeepSeek 多模态 ──► data/parsed/
```

## 文件

| 文件 | 作用 |
|---|---|
| `app.py` | FastAPI：上传、状态查询、问答接口，挂载前端 |
| `worker.py` | Kafka 消费者：解析 PDF、切块、更新状态 |
| `rag.py` | 切块、BM25 检索、DeepSeek 多模态问答 |
| `static/index.html` | 前端：上传、状态轮询、图文混排对话 |
| `data/` | 运行时生成：`uploads/` 原文件、`parsed/` 解析结果、`status/` 状态 JSON |

## 启动

```bash
cd hub-study/张義承/week14/h2

# 1. 依赖
pip install -r requirements.txt

# 2. 配置 Key（或直接 export）
cp .env.example .env
# 编辑 .env 填 DEEPSEEK_API_KEY

# 3. 确保 Redis/Kafka 已启动（本周前面那套）
docker ps | grep kafka

# 4. 终端 1：解析 worker
python worker.py

# 5. 终端 2：Web 服务
uvicorn app:app --port 8000

# 6. 浏览器
open http://127.0.0.1:8000
```

## 三个功能的实现位置

**功能 1：多 PDF 上传 → Kafka → 后端解析存储**

- 前端 `<input multiple>` 多选，`POST /api/upload` 一次提交多个文件
- `app.py` 每个文件落盘 `data/uploads/{doc_id}.pdf`，写状态 `pending`，向 `pdf-parse` 发一条消息
- `worker.py` 消费后调 MinerU；没装 MinerU 时自动降级 PyMuPDF（抽文本 + 内嵌图片）
- 解析结果写 `data/parsed/{doc_id}/content.md` + `chunks.json`，图片路径重写成 `/files/parsed/{doc_id}/...`

**功能 2：解析状态**

- 状态文件 `data/status/{doc_id}.json`：`pending` → `parsing` → `done` / `error`
- 前端每 2 秒轮询 `/api/docs`，渲染徽标：待解析 / 解析中 / 解析完成 / 解析失败
- 完成后展示块数、图片数、所用解析器

**功能 3：多模态问答**

- 检索：`rag.search()` 用 jieba 分词 + BM25 打分取 top-4 片段
- 图文混排输出：系统提示要求模型引用资料里出现过的图片路径，回答直接以 `![..](/files/...)` 形式内嵌，前端用 marked 渲染
- 图问一起送模型：前端 📎 选图 → 转 base64 data URL → `/api/chat` → 拼成 OpenAI 的 `image_url` content block 发给 DeepSeek
- 若模型不支持图片输入，`rag.answer()` 自动降级为纯文本再问一次，并在回答下方提示

## 说明

- MinerU 未安装也能完整跑通，只是解析质量降级；装好后重启 `worker.py` 即自动启用。
- 检索用内存 BM25，每次请求现读 `chunks.json`，文档量小完全够用；要换向量库只需改 `rag.search()`。
- `data/` 是运行时目录，不需要提交。
