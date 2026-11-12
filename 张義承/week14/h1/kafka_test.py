"""通过 Kafka 传递消息。

思路：
    Producer 把对话消息写到 topic；Consumer 订阅同一个 topic 按顺序读出来。
    消息 key 用 session_id，保证同一会话的消息落在同一分区、保持顺序。

用法：
    .venv/bin/python "hub-study/张義承/week14/h1/kafka_test.py"
    KAFKA_BOOTSTRAP=localhost:9092 KAFKA_TOPIC=chat-messages .venv/bin/python ...
"""

import json
import os
import sys
import uuid
from datetime import datetime

from kafka import KafkaConsumer, KafkaProducer
from kafka.admin import KafkaAdminClient, NewTopic
from kafka.errors import TopicAlreadyExistsError

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9092")
TOPIC = os.getenv("KAFKA_TOPIC", "chat-messages")
PARTITIONS = 3


def ensure_topic() -> None:
    admin = KafkaAdminClient(bootstrap_servers=KAFKA_BOOTSTRAP, request_timeout_ms=5000)
    try:
        admin.create_topics(
            [NewTopic(name=TOPIC, num_partitions=PARTITIONS, replication_factor=1)]
        )
        print(f"[Kafka] 已创建 topic '{TOPIC}'（{PARTITIONS} 个分区）")
    except TopicAlreadyExistsError:
        print(f"[Kafka] topic '{TOPIC}' 已存在")
    finally:
        admin.close()


def build_producer() -> KafkaProducer:
    return KafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP,
        key_serializer=lambda k: k.encode("utf-8"),
        value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
        request_timeout_ms=5000,
    )


def build_consumer(group_id: str) -> KafkaConsumer:
    return KafkaConsumer(
        TOPIC,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id=group_id,
        auto_offset_reset="earliest",
        enable_auto_commit=True,
        consumer_timeout_ms=10000,  # 10 秒没新消息就结束循环
        key_deserializer=lambda k: k.decode("utf-8") if k else None,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")),
    )


def main() -> int:
    try:
        ensure_topic()
        producer = build_producer()
    except Exception as e:
        print(f"[Kafka] 连接失败 {KAFKA_BOOTSTRAP} -> {type(e).__name__}: {e}")
        print("        请确认容器已启动：docker ps | grep kafka")
        return 1

    session_id = f"session-{uuid.uuid4().hex[:8]}"
    print(f"[Kafka] broker={KAFKA_BOOTSTRAP} topic={TOPIC} session={session_id}")

    # ---------- 生产 ----------
    messages = [
        {"role": "user", "content": "你好，我想了解 Kafka"},
        {"role": "assistant", "content": "Kafka 是一个分布式消息队列"},
        {"role": "user", "content": "消息是怎么保证顺序的？"},
        {"role": "assistant", "content": "同一分区内有序，用 key 决定分区"},
    ]
    print("\n[Producer] 发送消息：")
    for msg in messages:
        msg["session_id"] = session_id
        msg["ts"] = datetime.now().isoformat(timespec="seconds")
        meta = producer.send(TOPIC, key=session_id, value=msg).get(timeout=10)
        print(f"  -> partition={meta.partition} offset={meta.offset} | "
              f"{msg['role']}: {msg['content']}")
    producer.flush()
    producer.close()

    # ---------- 消费 ----------
    # 用独立的 group_id，保证总能从最早位置读回本次发送的消息
    group_id = f"test-group-{uuid.uuid4().hex[:8]}"
    print(f"\n[Consumer] group={group_id} 开始消费：")
    consumer = build_consumer(group_id)
    try:
        received = []
        for record in consumer:
            if record.value.get("session_id") != session_id:
                continue  # topic 里可能有别的会话的消息，这里只看自己的
            received.append(record)
            print(f"  <- p{record.partition}@{record.offset} "
                  f"key={record.key} | {record.value['role']}: {record.value['content']}")
    finally:
        consumer.close()

    print(f"\n[Consumer] 共收到 {len(received)} / {len(messages)} 条")
    if len(received) != len(messages):
        print("[Consumer] 数量不符，检查 broker 状态或 topic 配置")
        return 1

    order_ok = [r.value["content"] for r in received] == [m["content"] for m in messages]
    partitions = sorted({r.partition for r in received})
    print(f"[Consumer] 顺序一致: {order_ok}")
    print(f"[Consumer] 命中分区: {partitions}（同一 key 固定同一分区）")
    print("[Kafka] 测试完成 ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
