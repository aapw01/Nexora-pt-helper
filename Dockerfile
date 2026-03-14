# ── Stage 1: 构建前端 ──────────────────────────────────────────
FROM node:20-slim AS frontend-builder
WORKDIR /app
COPY web/package*.json ./
RUN npm install
COPY web/ .
ENV VITE_API_URL=""
RUN npm run build

# ── Stage 2: 安装 Python 依赖 ─────────────────────────────────
FROM python:3.13-slim AS python-deps
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
ENV UV_NO_DEV=1
RUN uv sync --locked

# ── Stage 3: 最终镜像 (Nginx + Python + supervisord) ─────────
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    PATH="/app/.venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
        nginx \
        supervisor \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/nginx/sites-enabled/default

WORKDIR /app

# Python 虚拟环境
COPY --from=python-deps /app/.venv ./.venv/

# Python 源码
COPY main.py ./
COPY api/ ./api/
COPY modules/ ./modules/

# 前端构建产物 → Nginx 静态目录
COPY --from=frontend-builder /app/dist /usr/share/nginx/html

# 配置文件
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY supervisord.conf /etc/supervisor/conf.d/app.conf

VOLUME ["/app/config", "/app/data"]

EXPOSE 80

CMD ["supervisord", "-n", "-c", "/etc/supervisor/conf.d/app.conf"]
