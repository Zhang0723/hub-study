# week15 / h2 · 情感陪伴流水线（openai-agents 版 · Docker）

代码取自 [../h1](../h1) 的 openai-agents 实现，去掉了 langgraph 分支，打包成一个镜像。
一个容器里跑三个进程，对外只暴露 8000。

```
容器
├── 进程1 emotion_service.py  :8101  情感识别
├── 进程2 respond_service.py  :8102  鼓励 / 排解 / 陪伴
└── 后端  backend.py          :8000  串联 1、2，托管前端页面
        run_all.py 负责把三个进程一起拉起来并转发 SIGTERM
```

## 基础镜像

```
swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/library/python:3.12-slim-linuxarm64
```

选择依据（本机实测）：

| 检查项 | 结论 |
| --- | --- |
| Docker Hub | **不可达**，`registry-1.docker.io` 超时，所以不能用 `python:3.12-slim` |
| 华为 SWR 镜像站 | 可达，本机 redis / kafka / es 三个镜像都来自这里 |
| 架构 | 镜像内 `aarch64` + glibc 2.36（Debian 12），与本机 arm64 原生一致，无需 QEMU |
| Python | 3.12.10，和本机 venv 的 3.12.1 同小版本线，wheel 标签一致 |
| 为什么不用 Alpine | 镜像站没有 `python:3.12-alpine-linuxarm64`；且 musl 会让 pydantic-core 等走源码编译 |
| PyPI | `files.pythonhosted.org` 不可达，容器内必须用清华源 `pypi.tuna.tsinghua.edu.cn` |

需要换基础镜像时：

```bash
docker build --build-arg BASE_IMAGE=<你的镜像> -t week15-h2-agents .
```

## 构建与运行

```bash
cd "hub-study/张義承/week15/h2"

docker build -t week15-h2-agents .

docker run -d --name w15h2 \
  -p 8000:8000 \
  -e DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" \
  week15-h2-agents
```

浏览器打开 <http://127.0.0.1:8000>。

**DEEPSEEK_API_KEY 是运行期注入的**，没有写进镜像。也可以改用 `--env-file`：

```bash
docker run -d --name w15h2 -p 8000:8000 --env-file .env week15-h2-agents
```

## 常用命令

```bash
docker logs -f w15h2                 # 看日志
docker ps --filter name=w15h2        # 状态（带 healthy）
curl http://127.0.0.1:8000/api/health
docker stop w15h2 && docker rm w15h2 # 停掉
```

## 环境变量

| 变量 | 默认值（Dockerfile 里已设） | 说明 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | 无，运行期必填 | 不传则 /api/chat 返回 500 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | OpenAI 兼容地址 |
| `DEEPSEEK_MODEL` | `deepseek-flash` | |
| `SERVICE_HOST` | `0.0.0.0` | uvicorn 监听地址 |
| `EMOTION_URL` / `RESPOND_URL` | `http://127.0.0.1:8101` / `:8102` | 容器内互访地址 |

## 踩过的坑

1. **uvicorn 必须绑 `0.0.0.0`**：绑 `127.0.0.1` 时容器内部自检能过，但 Docker 端口映射走 eth0，宿主机连不上，表现为 `curl` 返回 000。
2. **pip 必须用国内源**：`files.pythonhosted.org` 在本机不通，Dockerfile 里写了 `PIP_INDEX_URL`，否则构建卡在下载。
3. 容器里装到的是 openai-agents 0.25.0 / openai 3.55.1（本机 venv 是 0.19.4 / 2.46.0），已实测 `/analyze`、`/respond`、`/api/chat` 全链路正常。

## 文件

```
Dockerfile         镜像定义（含基础镜像选择说明）
.dockerignore
requirements.txt   只含 openai-agents 相关依赖，不含 langgraph
run_all.py         容器入口，起三个进程
backend.py         后端（固定走 agents_flow）
agents_flow.py     openai-agents 编排：两个 Agent + function_tool
emotion_service.py 进程1 情感识别
respond_service.py 进程2 鼓励/排解
service_client.py  跨进程 HTTP 客户端
prompts.py         提示词
llm.py             DeepSeek 客户端
static/index.html  前端页面
```
