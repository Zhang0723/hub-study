# openai-agents 版情感陪伴流水线
#
# 基础镜像说明（本机实测结论）：
#   1. Docker Hub 在本机不可达（registry-1.docker.io 超时），只能走华为 SWR 的 docker.io 镜像站；
#   2. 选 -linuxarm64 标签，与本机 arm64 原生匹配，无需 QEMU 模拟；
#   3. 用 Debian slim（glibc）而不是 Alpine，pydantic-core / uvloop 等可直接装 manylinux 轮子，
#      不用在容器里编译。
# 需要换基础镜像时用 --build-arg BASE_IMAGE=xxx 覆盖即可。
ARG BASE_IMAGE=swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/library/python:3.12-slim-linuxarm64
FROM ${BASE_IMAGE}

# files.pythonhosted.org 在本机不可达，必须走 PyPI 镜像源装依赖
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
    FRAMEWORK=openai-agents \
    EMOTION_URL=http://127.0.0.1:8101 \
    RESPOND_URL=http://127.0.0.1:8102

WORKDIR /app

# 先装依赖，利用层缓存
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

# 非 root 运行
RUN useradd -m -u 10001 app && chown -R app:app /app
USER app

EXPOSE 8000 8101 8102

HEALTHCHECK --interval=30s --timeout=6s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=5).status==200 else 1)"

# DEEPSEEK_API_KEY 运行期注入：docker run -e DEEPSEEK_API_KEY=sk-xxxx
CMD ["python", "run_all.py"]
