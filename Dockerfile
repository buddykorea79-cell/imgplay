# ffmpeg를 이미지에 포함하는 것이 이 Dockerfile의 존재 이유입니다.
# 로컬마다 다른 ffmpeg 버전·빌드 옵션 때문에 결과가 갈라지는 일을 없앱니다.
FROM node:22-slim AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
# opencv-python-headless는 GUI 의존성이 없지만 libGL 계열 최소 런타임은 필요합니다.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY backend/pyproject.toml ./backend/
COPY backend/app ./backend/app
RUN uv pip install --system --no-cache ./backend

COPY grade.yaml motion.yaml ./
COPY scripts/ ./scripts/
COPY --from=frontend /build/dist ./frontend/dist

ENV PVT_WORK_DIR=/app/work \
    PVT_RULES_DIR=/app \
    PVT_STATIC_DIR=/app/frontend/dist \
    PYTHONUNBUFFERED=1
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD curl -fsS http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--app-dir", "/app/backend"]
