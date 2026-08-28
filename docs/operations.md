# INTELX Operational Guide & Deployment Manual

This document details runtime configuration, environment variables, provider settings, backup strategies, and retention management for **INTELX**.

---

## 1. Environment Variables Configuration

| Variable | Type | Default | Description |
|---|---|---|---|
| `INTELX_ENV` | String | `development` | Deployment environment (`development`, `staging`, `production`). |
| `INTELX_MOCK_MODE` | Boolean | `true` | When `true`, runs fully offline with deterministic synthetic generators. |
| `INTELX_DB_URL` | String | `sqlite+aiosqlite:///./data/intelx.db` | Async database connection string (SQLite or PostgreSQL). |
| `INTELX_DATA_DIR` | String | `./data` | Local directory for raw file storage and exported report artifacts. |
| `INTELX_API_KEYS` | JSON String | `{"dev-admin-key": "admin", "dev-member-key": "member"}` | Initial seed API keys and role mapping. Stored as SHA-256 hashes only. |
| `INTELX_SECRET_KEY` | String | `insecure-dev-secret-key-...` | Secret used for HMAC session cookies and token signatures. |
| `INTELX_RATE_LIMIT_PER_MINUTE` | Integer | `120` | Sliding-window request rate limit per API key. |
| `INTELX_MAX_CONCURRENT_SUBQUESTIONS` | Integer | `3` | Maximum concurrent discovery subquestion worker branches. |
| `INTELX_RAW_RETENTION_DAYS` | Integer | `30` | Number of days before unreferenced raw HTML/PDF files are purged. |
| `OPENAI_API_KEY` | String | *Optional* | API key for OpenAI or OpenAI-compatible inference endpoints. |
| `OPENAI_BASE_URL` | String | *Optional* | Custom base URL for local/private models (e.g. vLLM, Ollama). |
| `ANTHROPIC_API_KEY` | String | *Optional* | API key for Anthropic Claude models. |
| `TAVILY_API_KEY` | String | *Optional* | API key for external web search discovery. |

---

## 2. Model Provider Setup

### 1. Offline Mock Mode (Zero-Config Default)
No API keys required. INTELX initializes with local heuristic generators:
```bash
export INTELX_MOCK_MODE=true
```

### 2. OpenAI / Compatible Inference (vLLM, Ollama, DeepSeek)
```bash
export INTELX_MOCK_MODE=false
export OPENAI_API_KEY="sk-..."
export OPENAI_BASE_URL="http://localhost:8000/v1"  # Optional private LLM endpoint
```

### 3. Anthropic Claude Inference
```bash
export INTELX_MOCK_MODE=false
export ANTHROPIC_API_KEY="sk-ant-..."
```

---

## 3. Storage, Backups & Disaster Recovery

### Database & File Directory
INTELX stores state in two primary locations:
1. **Relational Database**: `./data/intelx.db` (contains all entities, claims, citations, and audit chains).
2. **Raw File Ingestion Cache**: `./data/raw/` (contains ingested HTML, PDF, DOCX, CSV source documents).
3. **Generated Artifacts**: `./data/artifacts/` (contains generated Markdown reports, JSON packs, and CSV exports).

### Backup Procedure
To create a clean online backup of an active SQLite database without locking writers:
```bash
# Safely snapshot SQLite database using the VACUUM INTO command
sqlite3 ./data/intelx.db "VACUUM INTO './data/backups/intelx-$(date +%Y%m%d%H%M%S).db';"

# Archive data storage
tar -czf ./data/backups/data-files-$(date +%Y%m%d%H%M%S).tar.gz ./data/raw ./data/artifacts
```

---

## 4. Retention Management

The retention engine cleans up raw content older than `INTELX_RAW_RETENTION_DAYS` while preserving database claim citations and audit trails:

```bash
# Run CLI retention purge
intelx purge --days 30

# Or invoke the admin API
curl -X POST "http://localhost:8000/api/v1/admin/retention/purge?days=30" \
     -H "Authorization: Bearer <ADMIN_KEY>"
```
