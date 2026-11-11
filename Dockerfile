# ---------- 第一阶段：构建 Vue 前端 ----------
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- 第二阶段：Python 运行时同时提供 API 与 SPA ----------
FROM python:3.13-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    APPLICRAFT_DATA_DIR=/app/data \
    APPLICRAFT_STATIC_DIR=/app/static \
    APPLICRAFT_KNOWLEDGE_DIR=/knowledge
WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

COPY backend/app ./app
COPY knowledge/ /knowledge/
COPY --from=web /web/dist ./static
RUN mkdir -p /app/data

EXPOSE 8000
VOLUME ["/app/data"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
