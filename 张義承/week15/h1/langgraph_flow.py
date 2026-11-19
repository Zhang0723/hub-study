"""LangGraph 版编排：后端进程用它串联「进程1」和「进程2」。

图结构（条件分支就是「正向则鼓励，负面则排解」）：

    START
      │
    emotion  ← 进程1：情感识别
      │
    [route] ── positive ──> encourage ← 进程2（mode=encourage）
      │        negative ──> comfort   ← 进程2（mode=comfort）
      │        neutral  ──> neutral   ← 进程2（mode=neutral）
      └──────────────────────────────> END

对外只暴露一个 run(text) 函数，backend.py 直接调用。
"""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

import service_client as svc
from prompts import MODE_TITLES


class State(TypedDict, total=False):
    text: str
    emotion: dict      # 进程1 的输出
    mode: str          # 进程2 的回应模式
    reply: str         # 进程2 的输出
    trace: list[str]   # 每一步的执行轨迹，前端展示用


# ---------------------------------------------------------------- 节点
def node_emotion(state: State) -> dict:
    """进程1：情感识别。"""
    emo = svc.analyze_emotion(state["text"])
    mode = svc.pick_mode(emo["sentiment"])
    trace = list(state.get("trace", []))
    trace.append(
        f"进程1 情感识别 → {emo['sentiment']}（{emo['emotion']}，置信度 {emo['confidence']}）"
    )
    return {"emotion": emo, "mode": mode, "trace": trace}


def route_by_sentiment(state: State) -> str:
    """条件边：正向走鼓励，负面走排解，其余走陪伴。"""
    return state.get("mode", "neutral")


def _respond_node(state: State, mode: str) -> dict:
    emo = state["emotion"]
    reply = svc.generate_reply(
        state["text"], emo["sentiment"], emo.get("emotion", ""), mode
    )
    trace = list(state.get("trace", []))
    trace.append(f"进程2 {MODE_TITLES[mode]} → 生成 {len(reply)} 字回应")
    return {"reply": reply, "mode": mode, "trace": trace}


def node_encourage(state: State) -> dict:
    return _respond_node(state, "encourage")


def node_comfort(state: State) -> dict:
    return _respond_node(state, "comfort")


def node_neutral(state: State) -> dict:
    return _respond_node(state, "neutral")


# ---------------------------------------------------------------- 建图
def build_graph():
    g = StateGraph(State)
    g.add_node("emotion", node_emotion)
    g.add_node("encourage", node_encourage)
    g.add_node("comfort", node_comfort)
    g.add_node("neutral", node_neutral)

    g.add_edge(START, "emotion")
    g.add_conditional_edges(
        "emotion",
        route_by_sentiment,
        {"encourage": "encourage", "comfort": "comfort", "neutral": "neutral"},
    )
    for n in ("encourage", "comfort", "neutral"):
        g.add_edge(n, END)
    return g.compile()


GRAPH = build_graph()


def run(text: str) -> dict:
    """供 backend 调用：返回 {text, emotion, mode, reply, trace, framework}。"""
    state = GRAPH.invoke({"text": text, "trace": []})
    return {
        "text": text,
        "emotion": state["emotion"],
        "mode": state["mode"],
        "reply": state["reply"],
        "trace": state["trace"],
        "framework": "langgraph",
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
        print(f"  情感：{out['emotion']['sentiment']} / {out['emotion']['emotion']}")
        print(f"  模式：{MODE_TITLES[out['mode']]}")
        print(f"  回复：{out['reply']}")
        for t in out["trace"]:
            print(f"    - {t}")
