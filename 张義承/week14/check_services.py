"""检查本地 Redis / Kafka 连通性。

用法:
    .venv/bin/python "hub-study/张義承/week14/check_services.py"
"""

import sys

REDIS_HOST, REDIS_PORT = "localhost", 6379
KAFKA_BOOTSTRAP = "localhost:9092"
TOPIC = "healthcheck"

ok = True


def check_redis() -> None:
    global ok
    try:
        import redis
    except ImportError:
        print("[Redis] SKIP  未安装 redis，请先 pip install 'redis[hiredis]'")
        ok = False
        return

    try:
        r = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            socket_connect_timeout=3,
            decode_responses=True,
        )
        print(f"[Redis] PING -> {r.ping()}")
        r.set("healthcheck", "ok", ex=30)
        print(f"[Redis] SET/GET -> {r.get('healthcheck')}")
        print(f"[Redis] 版本 -> {r.info('server')['redis_version']}")
        print("[Redis] OK")
    except Exception as e:
        ok = False
        print(f"[Redis] FAIL {type(e).__name__}: {e}")


def check_kafka() -> None:
    global ok
    try:
        from kafka import KafkaConsumer, KafkaProducer
        from kafka.admin import KafkaAdminClient, NewTopic
        from kafka.errors import TopicAlreadyExistsError
    except ImportError:
        print("[Kafka] SKIP  未安装 kafka-python，请先 pip install kafka-python")
        ok = False
        return

    try:
        admin = KafkaAdminClient(bootstrap_servers=KAFKA_BOOTSTRAP, request_timeout_ms=5000)
        try:
            admin.create_topics([NewTopic(name=TOPIC, num_partitions=1, replication_factor=1)])
            print(f"[Kafka] 创建 topic '{TOPIC}'")
        except TopicAlreadyExistsError:
            print(f"[Kafka] topic '{TOPIC}' 已存在")
        admin.close()
    except Exception as e:
        ok = False
        print(f"[Kafka] FAIL 连不上 broker {KAFKA_BOOTSTRAP}: {type(e).__name__}: {e}")
        return

    try:
        producer = KafkaProducer(
            bootstrap_servers=KAFKA_BOOTSTRAP,
            request_timeout_ms=5000,
        )
        producer.send(TOPIC, b"ping").get(timeout=10)
        producer.flush()
        print("[Kafka] 发送 1 条消息成功")

        consumer = KafkaConsumer(
            TOPIC,
            bootstrap_servers=KAFKA_BOOTSTRAP,
            auto_offset_reset="earliest",
            consumer_timeout_ms=8000,
            group_id="healthcheck-group",
        )
        msgs = [m.value for m in consumer]
        consumer.close()
        if msgs:
            print(f"[Kafka] 收到 {len(msgs)} 条: {msgs[:3]}")
            print("[Kafka] OK")
        else:
            ok = False
            print("[Kafka] FAIL 消息发送成功但消费不到")
    except Exception as e:
        ok = False
        print(f"[Kafka] FAIL {type(e).__name__}: {e}")


if __name__ == "__main__":
    check_redis()
    check_kafka()
    print("\n结果:", "全部通过" if ok else "有失败项")
    sys.exit(0 if ok else 1)
