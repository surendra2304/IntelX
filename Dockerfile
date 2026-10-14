# Multi-stage Dockerfile for IntelX Intelligence Platform
# Build stage: Install dependencies in a clean virtualenv
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml requirements.txt README.md ./
COPY intelx/ ./intelx/
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir .

# Final stage: Minimal hardened runtime image
FROM python:3.11-slim AS runner

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000 \
    PATH="/opt/venv/bin:$PATH" \
    INTELX_DATA_DIR="/app/data" \
    INTELX_DB_URL="sqlite+aiosqlite:////app/data/intelx.db"

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    sqlite3 \
    tini \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv

RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/data /app/data/raw /app/data/artifacts /app/data/uploads && \
    chown -R appuser:appuser /app

COPY --chown=appuser:appuser . /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

ENTRYPOINT ["tini", "--", "python", "-m", "intelx.cli.main"]
CMD ["serve"]
