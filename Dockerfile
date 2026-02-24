# ============================================================
# code-autonomy — Multi-stage Docker build
# ============================================================
# Stage 1: Python agent (main workload)
# Stage 2: (optional) WebUI — uncomment if webui/ has a package.json
# Stage 3: Final image combining both
# ============================================================

# --------------- Stage 1: Python agent ---------------
FROM python:3.11-slim AS agent

# System dependencies: git (clone/push), ssh (Bitbucket SSH)
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        openssh-client \
        curl \
        jq \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies (layer-cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir \
        javalang>=0.13.0 \
        rank-bm25>=0.2.2 \
        boto3>=1.34.0 \
        opensearch-py>=2.4.0 \
        requests-aws4auth>=1.2.3 \
    || true

# Copy application source
COPY src/ src/
COPY main.py fork_and_run.py ./
COPY scripts/ scripts/
COPY examples/ examples/
COPY tests/ tests/

# Create directories for runtime data
RUN mkdir -p /app/workspace /data/knowledge /data/traces /data/consciousness /data/code-index

# Default config template (overridden at runtime via mount or env)
COPY config.example.ini /app/config.example.ini

# Entrypoint script
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

# --------------- Final stage ---------------
FROM agent AS final

# Labels for ECR / container registries
LABEL maintainer="code-autonomy"
LABEL description="Autonomous code generation agent with LLM-powered analysis"

# Set HOME to persistent volume so Path.home() writes land there
ENV HOME=/data

# Environment defaults (override at runtime)
# NOTE: each ENV line is separate — inline comments break multi-line ENV syntax
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV WORK_DIR=/app/workspace
ENV CONSCIOUSNESS_CACHE_DIR=/data/consciousness
ENV CODE_INDEX_CACHE_DIR=/data/code-index
ENV KNOWLEDGE_STORAGE_DIR=/data/knowledge
ENV TRACING_STORAGE_DIR=/data/traces

# Health check — verifies Python and imports work
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "from src.config_loader import load_config; print('ok')" || exit 1

EXPOSE 3000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["--agent", "--config", "/app/config.ini"]
