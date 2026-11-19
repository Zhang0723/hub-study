"""容器入口：在一个容器里同时起三个进程。

    进程1 emotion_service.py  :8101
    进程2 respond_service.py  :8102
    后端  backend.py          :8000（对外只暴露这个端口）

docker stop 发来的 SIGTERM 会转发给三个子进程，任一子进程异常退出则整体退出。
"""

import os
import signal
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))

SERVICES = [
    ("进程1 情感识别", "emotion_service.py"),
    ("进程2 鼓励排解", "respond_service.py"),
    ("后端+前端", "backend.py"),
]

_procs: list[tuple[str, subprocess.Popen]] = []


def shutdown(code: int = 0) -> None:
    for _, p in _procs:
        if p.poll() is None:
            p.terminate()
    for _, p in _procs:
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
    sys.exit(code)


def _on_signal(signum, frame):  # noqa: ARG001
    print(f"[run_all] 收到信号 {signum}，停止全部进程", flush=True)
    shutdown(0)


def main() -> None:
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    for name, script in SERVICES:
        p = subprocess.Popen(
            [sys.executable, "-u", os.path.join(BASE, script)],
            cwd=BASE,
            env=os.environ.copy(),
        )
        _procs.append((name, p))
        print(f"[run_all] 启动 {name} pid={p.pid}", flush=True)

    while True:
        for name, p in _procs:
            code = p.poll()
            if code is not None:
                print(f"[run_all] {name} 退出（code={code}），停止全部", flush=True)
                shutdown(1)
        time.sleep(1)


if __name__ == "__main__":
    main()
