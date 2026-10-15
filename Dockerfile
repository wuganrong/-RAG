# =============================================================================
# 应用镜像：Python 3.10 (slim) + 项目依赖 + 应用代码（多阶段构建）
# 不再依赖 ghcr.io/astral-sh/uv，改用 python:3.10-slim + pip 装 uv
#
# 构建命令：docker compose build
# =============================================================================

# ---- 阶段 1：构建 Python 依赖（构建工具不进最终镜像） ----
FROM python:3.10-slim AS builder

# 替换 Debian 镜像源为阿里云（加速国内 apt 下载）
# bookworm 用 /etc/apt/sources.list.d/debian.sources（DEB822 格式）
RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources; \
    fi && \
    if [ -f /etc/apt/sources.list ]; then \
      sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list; \
    fi

# 安装编译依赖（仅 builder 阶段需要）
RUN apt-get update && apt-get install -y --no-install-recommends --fix-missing \
        build-essential \
        gcc \
        g++ \
        pkg-config \
        libmariadb-dev-compat \
        libssl-dev \
        libffi-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# 配置 pip 走阿里云源（避免拉 pypi.org 超时）
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && \
    pip config set global.trusted-host mirrors.aliyun.com

# 安装 uv（走阿里云源，长超时）
RUN pip install --no-cache-dir --default-timeout=100 uv || \
    pip install --no-cache-dir --default-timeout=100 -i https://mirrors.aliyun.com/pypi/simple/ uv

WORKDIR /app

# 同步 Python 依赖（pyproject.toml 已配置清华 PyPI + pytorch-cu130 索引）
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ---- 阶段 2：运行时镜像 ----
FROM python:3.10-slim

# 替换 Debian 镜像源为阿里云
RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources; \
    fi && \
    if [ -f /etc/apt/sources.list ]; then \
      sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list; \
    fi

# 安装运行时依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        libmariadb-dev-compat \
        libssl3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/code

# 从 builder 阶段复制 Python 虚拟环境（含 uv 和所有依赖）
COPY --from=builder /app/.venv /app/.venv

# 环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# ---- 复制项目代码 ----
COPY . ./

# 启动脚本（去掉 Windows CRLF 行尾，否则 bash 找不到）
COPY docker/entrypoint.sh /entrypoint.sh
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -sf http://localhost:9380/api/schema/ || exit 1

EXPOSE 9380

ENTRYPOINT ["/entrypoint.sh"]
CMD ["django"]