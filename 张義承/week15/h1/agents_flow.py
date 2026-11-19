"""openai-agents 版编排：后端进程用它串联「进程1」和「进程2」。

思路：
    两个 Agent 各自只做一件事，通过 function_tool 调用对应的独立进程（HTTP），
    再用 tool_use_behavior="stop_on_first_tool" 让工具结果直接作为该 Agent 的最终输出，
    保证「进程1 识别 → 按结论选择鼓励/排解 → 进程2 生成」这条链路是确定的。

    Agent「进程1-情感识别」 ──tool──> POST /analyze   (进程1)
              │
        sentiment → positive / negative / neutral
              │
    Agent「进程2-鼓励|排解|陪伴」 ──tool──> POST /respond (进程2)

对外同样只暴露 run(text) 函数，与 langgraph_flow.run 返回结构一致。
"""

import json
import re

from agents import Agent, Runner, function_tool, set_default_openai_client, set_tracing_disabled
from openai import AsyncOpenAI

import llm
import service_client as svc
from prompts import MODE_TITLES

_configured = False


def _configure() -> None:
    """把 agents SDK 默认的 OpenAI 客户端指向 DeepSeek。"""
    global _configured
    if _configured:
        return
    set_tracing_disabled(True)  # 不上报 OpenAI tracing，避免额外依赖
    set_default_openai_client(AsyncOpenAI(api_key=llm.api_key(), base_url=llm.base_url()))
    _configured = True


def _parse_json(text: str) -> dict | None:
    if not text:
        return None
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.S).strip()
    m = re.search(r"\{.*\}", s, flags=re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def run(text: str) -> dict:
    """供 backend 调用：返回结构与 langgraph_flow.run 相同。"""
    _configure()
    model = llm.model()
    captured: dict = {"emotion": None, "reply": None}
    trace: list[str] = []

    # ---------------- Agent 1：调用进程1 ----------------
    @function_tool
    def analyze_emotion_tool() -> str:
        """调用「进程1 情感识别」进程，分析用户原话的情感。无需参数，直接调用。"""
        result = svc.analyze_emotion(text)
        captured["emotion"] = result
        return json.dumps(result, ensure_ascii=False)

    emotion_agent = Agent(
        name="进程1-情感识别",
        instructions=(
            "你唯一的职责是调用 analyze_emotion_tool 工具去识别用户的情感。"
            "必须调用该工具，不要自己判断，也不要输出任何其它内容。"
        ),
        tools=[analyze_emotion_tool],
        tool_use_behavior="stop_on_first_tool",
        model=model,
    )

    r1 = Runner.run_sync(emotion_agent, input=f"用户原话：{text}", max_turns=3)
    emo = captured["emotion"] or _parse_json(str(r1.final_output))
    if not emo:
        # 兜底：Agent 没有走工具时，直接问进程1
        emo = svc.analyze_emotion(text)
    emo.setdefault("sentiment", "neutral")
    trace.append(
        f"Agent 进程1-情感识别 → {emo['sentiment']}"
        f"（{emo.get('emotion', '')}，置信度 {emo.get('confidence', '-')}）"
    )

    # ---------------- 按情感结论决定进程2 的模式 ----------------
    mode = svc.pick_mode(emo["sentiment"])

    # ---------------- Agent 2：调用进程2 ----------------
    @function_tool
    def generate_reply_tool() -> str:
        """调用「进程2 鼓励/排解」进程生成回应。无需参数，直接调用。"""
        reply = svc.generate_reply(
            text, emo["sentiment"], emo.get("emotion", ""), mode
        )
        captured["reply"] = reply
        return reply

    respond_agent = Agent(
        name=f"进程2-{MODE_TITLES[mode]}",
        instructions=(
            f"你唯一的职责是调用 generate_reply_tool 工具生成回应，模式为「{MODE_TITLES[mode]}」。"
            "必须调用该工具，不要自己写回应。"
        ),
        tools=[generate_reply_tool],
        tool_use_behavior="stop_on_first_tool",
        model=model,
    )

    r2 = Runner.run_sync(
        respond_agent,
        input=f"用户原话：{text}\n情感：{emo['sentiment']}（{emo.get('emotion', '')}）",
        max_turns=3,
    )
    reply = captured["reply"] or (str(r2.final_output).strip() if r2.final_output else "")
    if not reply:
        reply = svc.generate_reply(text, emo["sentiment"], emo.get("emotion", ""), mode)
    trace.append(f"Agent 进程2-{MODE_TITLES[mode]} → 生成 {len(reply)} 字回应")

    return {
        "text": text,
        "emotion": emo,
        "mode": mode,
        "reply": reply,
        "trace": trace,
        "framework": "openai-agents",
    }


# ---------------------------------------------------------------- 命令行自测
if __name__ == "__main__":
    import sys

    samples = sys.argv[1:] or [
        "今天面试通过了，特别开心！",
        "最近作业太多了，压力好大，晚上睡不着。",
        "明天几点开会？",
    ]
    for s in samples:
        print(f"\n用户：{s}")
        out = run(s)
        print(f"  情感：{out['emotion']['sentiment']} / {out['emotion'].get('emotion')}")
        print(f"  模式：{MODE_TITLES[out['mode']]}")
        print(f"  回复：{out['reply']}")
        for t in out["trace"]:
            print(f"    - {t}")
