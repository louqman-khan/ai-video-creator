# AI Video Creator, hosted mode. Build:  docker build -t avc .      Run: see deploy/docker-compose.yml and docs/hosting.md
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 PIP_NO_CACHE_DIR=1 MODE=hosted WORK_DIR=/data/work PROJECTS_DIR=/data/projects HF_HOME=/data/cache/hf XDG_CACHE_HOME=/data/cache FRONTEND_DIST=/app/frontend/dist
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core curl && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 avc && mkdir -p /data && chown avc /data
WORKDIR /app
COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/app backend/app
COPY backend/cli backend/cli
RUN pip install -e './backend[kokoro]'   # editable: the app finds assets/ and the web build next to backend/ (config.ROOT = /app)
COPY assets/fonts assets/fonts
RUN mkdir -p assets/models && chown -R avc /app/assets
COPY --from=web /web/dist frontend/dist
USER avc
RUN avc fetch-models --kokoro || avc fetch-models || true
VOLUME /data
EXPOSE 8742
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s CMD curl -fsS http://127.0.0.1:8742/api/health || exit 1
CMD ["avc", "app", "--no-browser", "--host", "0.0.0.0", "--port", "8742"]
