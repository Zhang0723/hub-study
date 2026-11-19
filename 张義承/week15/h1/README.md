# week15 / h1 · 情感陪伴流水线（LangGraph + openai-agents）

同一套「情感识别 → 鼓励/排解」流程，用 **langgraph** 和 **openai-agents** 各实现一遍，
由后端进程按请求选择其中一套编排。

## 架构

```
浏览器（前端进程）
   │  POST /api/chat {text, framework}
   ▼
backend.py  ← 后端进程 :8000   ┌── langgraph_flow.run()      图编排
   │                            └── agents_flow.run()         Agent 编排
   │  HTTP
   ├──────────────► 进程1 emotion_service.py  :8101  POST /analyze  情感识别
   └──────────────► 进程2 respond_service.py  :8102  POST /respond  鼓励 / 排解 / 陪伴
```

| 角色 | 文件 | 端口 | 职责 |
| --- | --- | --- | --- |
| 进程1 | `emotion_service.py` | 8101 | 调 DeepSeek 输出 `{sentiment, emotion, confidence, reason}` |
| 进程2 | `respond_service.py` | 8102 | 按 `mode` 生成回应：正向→鼓励、负面→排解、其它→陪伴 |
| 后端 | `backend.py` | 8000 | 接收前端输入，选择框架串联进程1、进程2，托管前端页面 |
| 前端 | `static/index.html` | — | 输入框、框架切换、情感/策略标签、调用链路展示 |

两套编排都只做「串联 + 分支」，真正的模型调用在进程1、进程2 里，所以换框架不影响子进程。

### 两个框架怎么表达这条链路

**langgraph**（`langgraph_flow.py`）— 状态图 + 条件边：

```
START → emotion(进程1) ─┬─ positive → encourage(进程2, mode=encourage)
                        ├─ negative → comfort  (进程2, mode=comfort)
                        └─ neutral  → neutral  (进程2, mode=neutral)
                                                                → END
```

**openai-agents**（`agents_flow.py`）— 两个 Agent，各自通过 `function_tool` 调用一个子进程，
用 `tool_use_behavior="stop_on_first_tool"` 把工具结果直接当 Agent 的最终输出：

```
Agent「进程1-情感识别」 ──tool──> POST /analyze
        │ 拿到 sentiment，代码决定 mode
Agent「进程2-鼓励/排解/陪伴」 ──tool──> POST /respond
```

## 运行

```bash
cd "hub-study/张義承/week15/h1"

# 1) 依赖（本机已有可跳过）
python -m pip install -r requirements.txt

# 2) 配置 Key：环境变量或复制 .env.example 为 .env
export DEEPSEEK_API_KEY=sk-xxxx
export DEEPSEEK_BASE_URL=https://api.deepseek.com   # 可选
export DEEPSEEK_MODEL=deepseek-flash                # 可选

# 3) 一键启动三个进程
./start_all.sh
# 等价于分别运行：
#   python emotion_service.py
#   python respond_service.py
#   python backend.py
```

浏览器打开 <http://127.0.0.1:8000>，在右上角切 LangGraph / openai-agents。

## 命令行单独跑

```bash
# 先起两个子进程
python emotion_service.py &
python respond_service.py &

# langgraph 版
python langgraph_flow.py "今天面试通过了，特别开心！" "作业太多，压力好大"
# openai-agents 版
python agents_flow.py "今天面试通过了，特别开心！" "作业太多，压力好大"
```

## 接口

```bash
# 情感识别（进程1）
curl -X POST http://127.0.0.1:8101/analyze \
  -H 'Content-Type: application/json' -d '{"text":"作业好多，压力大"}'
# {"sentiment":"negative","emotion":"焦虑","confidence":0.95,"reason":"...","raw":"..."}

# 回应生成（进程2）
curl -X POST http://127.0.0.1:8102/respond \
  -H 'Content-Type: application/json' \
  -d '{"text":"作业好多，压力大","sentiment":"negative","emotion":"焦虑","mode":"comfort"}'
# {"reply":"其实我挺理解...","mode":"comfort"}

# 后端编排
curl -X POST http://127.0.0.1:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"text":"作业好多，压力大","framework":"langgraph"}'
# {"text":..., "emotion":{...}, "mode":"comfort", "reply":"...", "trace":[...], "framework":"langgraph"}

# 健康检查
curl http://127.0.0.1:8000/api/health
```

## 文件

```
emotion_service.py   进程1 情感识别（FastAPI :8101）
respond_service.py   进程2 鼓励/排解（FastAPI :8102）
backend.py           后端进程（:8000），按 framework 选择编排
langgraph_flow.py    LangGraph 实现：StateGraph + 条件边
agents_flow.py       openai-agents 实现：两个 Agent + function_tool
service_client.py    跨进程 HTTP 客户端（两个框架共用）
prompts.py           情感识别、鼓励、排解、陪伴四段提示词
llm.py               DeepSeek 客户端（OpenAI 兼容接口）
static/index.html    前端页面
start_all.sh         一键启动三个进程
```
