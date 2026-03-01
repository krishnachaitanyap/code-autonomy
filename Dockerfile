# Stage 1: Build Next.js static export
FROM node:20-alpine AS frontend-builder
WORKDIR /build
COPY webui/package.json webui/package-lock.json ./
RUN npm ci --production=false
COPY webui/ ./
ENV NEXT_PUBLIC_API_URL=/api NEXT_BUILD_MODE=export
RUN npm run build

# Stage 2: Python runtime
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends git curl && rm -rf /var/lib/apt/lists/*
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/
COPY main.py ./
COPY config.example.ini ./
COPY --from=frontend-builder /build/out/ ./static/
RUN mkdir -p /data /app/workspace && chown -R appuser:appuser /app /data
ENV DATABASE_URL=sqlite:////data/autonomy.db PYTHONUNBUFFERED=1
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1
CMD ["uvicorn", "src.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
