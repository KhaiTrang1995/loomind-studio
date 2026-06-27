# ============================================================
# Loomind Experience Engine — Multi-stage Dockerfile
# v0.3.0 — Phase 11 Agentic Brain
# ============================================================

# ── Stage 1: Build ──────────────────────────────────────────
FROM python:3.10-slim AS builder

WORKDIR /app

RUN pip install --no-cache-dir --upgrade pip

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application source
COPY src/ src/
COPY seed_data.py ./
COPY .env.example .env

# ── Stage 2: Runtime ────────────────────────────────────────
FROM python:3.10-slim AS runtime

# Security: non-root user
RUN groupadd -r loomind && \
    useradd -r -g loomind -d /app -s /sbin/nologin loomind

WORKDIR /app

# Installed packages + binaries from builder
COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Application files
COPY --from=builder /app/src       src/
COPY --from=builder /app/seed_data.py seed_data.py
COPY --from=builder /app/.env      .env

# Data and log directories — engine-data volume is mounted here at runtime.
# /app/data persists: goals.db (SQLite WAL) + ui-settings.json (config overrides).
RUN mkdir -p /app/data /app/logs && \
    chown -R loomind:loomind /app

USER loomind

# ── Environment defaults ─────────────────────────────────────
ENV ENGINE_HOST=0.0.0.0
ENV ENGINE_PORT=8082
ENV QDRANT_MODE=server
ENV QDRANT_URL=http://qdrant:6333
ENV GOAL_DB_PATH=/app/data/goals.db
ENV NOTIFICATION_ENABLED=false
# MUST stay at 1 — BackgroundWorker and EventBus are in-process singletons.
ENV UVICORN_WORKERS=1

EXPOSE 8082

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8082/health').raise_for_status()" || exit 1

CMD ["sh", "-c", "exec python -m uvicorn src.main:app \
  --host ${ENGINE_HOST} \
  --port ${ENGINE_PORT} \
  --workers ${UVICORN_WORKERS} \
  --log-level ${ENGINE_LOG_LEVEL:-info} \
  --limit-concurrency 200 \
  --backlog 2048"]
