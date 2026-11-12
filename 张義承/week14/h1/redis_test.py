"""用 Redis 存储历史对话。

思路：
    每个会话一个 List，key 为 chat:history:{session_id}，
    每条消息序列化成 JSON 后 RPUSH 进列表，按写入顺序天然就是对话顺序。
    读取时 LRANGE 即可拿到完整历史，或只取最后 N 条做上下文窗口。

用法：
    .venv/bin/python "hub-study/张義承/week14/h1/redis_test.py"
    REDIS_HOST=127.0.0.1 REDIS_PORT=6379 .venv/bin/python ...
"""

import json
import os
import sys
import uuid
from datetime import datetime

import redis

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
SESSION_TTL = 3600  # 会话 1 小时后过期，避免测试数据堆积
KEY_PREFIX = "chat:history:"


def get_client() -> redis.Redis:
    client = redis.Redis(
        host=REDIS_HOST,
        port=REDIS_PORT,
        socket_connect_timeout=3,
        decode_responses=True,
    )
    client.ping()  # 连不上会直接抛异常，早点报错
    return client


def history_key(session_id: str) -> str:
    return f"{KEY_PREFIX}{session_id}"


def save_message(client: redis.Redis, session_id: str, role: str, content: str) -> None:
    """追加一条消息到会话历史末尾，并刷新过期时间。"""
    message = {
        "role": role,
        "content": content,
        "ts": datetime.now().isoformat(timespec="seconds"),
    }
    key = history_key(session_id)
    with client.pipeline() as pipe:
        pipe.rpush(key, json.dumps(message, ensure_ascii=False))
        pipe.expire(key, SESSION_TTL)
        pipe.execute()


def get_history(client: redis.Redis, session_id: str, limit: int | None = None) -> list[dict]:
    """读取会话历史。limit 给定时只返回最近 limit 条（模拟上下文窗口）。"""
    key = history_key(session_id)
    raw = client.lrange(key, -limit, -1) if limit else client.lrange(key, 0, -1)
    return [json.loads(item) for item in raw]


def clear_history(client: redis.Redis, session_id: str) -> None:
    client.delete(history_key(session_id))


def print_history(messages: list[dict], title: str) -> None:
    print(f"\n{title}（{len(messages)} 条）")
    print("-" * 56)
    for m in messages:
        print(f"  [{m['ts']}] {m['role']:<9} | {m['content']}")
    print("-" * 56)


def main() -> int:
    try:
        client = get_client()
    except Exception as e:
        print(f"[Redis] 连接失败 {REDIS_HOST}:{REDIS_PORT} -> {type(e).__name__}: {e}")
        print("        请确认容器已启动：docker ps | grep redis")
        return 1

    print(f"[Redis] 已连接 {REDIS_HOST}:{REDIS_PORT} "
          f"(redis {client.info('server')['redis_version']})")

    session_id = f"demo-{uuid.uuid4().hex[:8]}"
    print(f"[Redis] 本次会话 session_id = {session_id}")

    # 模拟三轮问答：每一步都把用户消息和助手回复写进 Redis
    conversation = [
        ("user", "你好，我叫张三，在做 Redis 的作业"),
        ("assistant", "你好张三，有什么可以帮你？"),
        ("user", "我想把我们的对话存到 Redis 里"),
        ("assistant", "好的，已用 List 结构把每条消息追加保存"),
        ("user", "那怎么只取最近几条做上下文？"),
        ("assistant", "用 LRANGE key -N -1 取末尾 N 条就行"),
    ]
    for role, content in conversation:
        save_message(client, session_id, role, content)
        print(f"  写入 -> {role}: {content}")

    full = get_history(client, session_id)
    print_history(full, "完整会话历史")

    recent = get_history(client, session_id, limit=4)
    print_history(recent, "最近 4 条（作为上下文窗口发给模型）")

    key = history_key(session_id)
    print(f"\n[Redis] key        = {key}")
    print(f"[Redis] 类型/长度  = {client.type(key)} / {client.llen(key)}")
    print(f"[Redis] 剩余 TTL   = {client.ttl(key)} 秒")
    print(f"[Redis] 当前库中会话数 = {len(client.keys(KEY_PREFIX + '*'))}")

    # 不同会话之间互不影响
    other = f"demo-{uuid.uuid4().hex[:8]}"
    save_message(client, other, "user", "这是另一个会话")
    print(f"[Redis] 新建另一个会话 {other}，条数 = {len(get_history(client, other))}")
    print(f"[Redis] 原会话条数仍为 {len(get_history(client, session_id))}（互不干扰）")

    clear_history(client, session_id)
    clear_history(client, other)
    print(f"\n[Redis] 已清理测试数据，剩余会话数 = {len(client.keys(KEY_PREFIX + '*'))}")
    print("[Redis] 测试完成 ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
