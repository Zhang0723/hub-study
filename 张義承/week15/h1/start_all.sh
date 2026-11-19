#!/usr/bin/env bash
# 一键启动三个进程：进程1(8101)、进程2(8102)、后端(8000)
# 用法：./start_all.sh          默认 python3
#      PYTHON=/path/to/python ./start_all.sh
set -euo pipefail

cd "$(dirname "$0")"
PYTHON="${PYTHON:-python3}"

if [ -z "${DEEPSEEK_API_KEY:-}" ] && [ ! -f .env ]; then
  echo "缺少 DEEPSEEK_API_KEY：请 export 该变量，或在同目录创建 .env（见 .env.example）"
  exit 1
fi

pids=()
cleanup() {
  echo
  echo "正在停止所有进程…"
  for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
  echo "已停止。"
}
trap cleanup EXIT INT TERM

"$PYTHON" emotion_service.py & pids+=($!)
"$PYTHON" respond_service.py & pids+=($!)
"$PYTHON" backend.py & pids+=($!)

echo "进程1 情感识别  http://127.0.0.1:8101"
echo "进程2 鼓励排解  http://127.0.0.1:8102"
echo "后端 + 前端     http://127.0.0.1:8000"
echo "Ctrl+C 停止全部。"
wait
