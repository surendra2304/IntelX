# Multi-stage Dockerfile for INTELX Intelligence Platform
# Build stage: Install dependencies in a clean virtualenv
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir .

# Final stage: Minimal runtime image
FROM python:3.11-slim AS runner

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    sqlite3 \
    tini \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV INTELX_DATA_DIR="/app/data"
ENV INTELX_DB_URL="sqlite+aiosqlite:////app/data/intelx.db"

# Create unprivileged application user
RUN groupadd -g 10001 intelx && \
    useradd -u 10001 -g intelx -s /bin/bash -m intelx && \
    mkdir -p /app/data /app/data/raw /app/data/artifacts /app/data/uploads && \
    chown -R intelx:intelx /app

COPY --chown=intelx:intelx . /app

# Switch to non-root user
USER intelx

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/healthz || exit 1

ENTRYPOINT ["tini", "--", "python", "-m", "intelx.cli.main"]
CMD ["serve"]
