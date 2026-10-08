# INTELX Operational Guide & Deployment Manual

This document details runtime configuration, environment variables, provider settings, backup strategies, and retention management for **INTELX**.

---

## 1. Environment Variables Configuration

| Variable | Type | Default | Description |
|---|---|---|---|
| `INTELX_ENV` | String | `development` | Deployment environment (`development`, `staging`, `production`). |
| `INTELX_MOCK_MODE` | Boolean | `true` | When `true`, runs fully offline with deterministic synthetic generators. Production must set this to `false`. |
| `INTELX_ALLOW_MOCK_FALLBACK` | Boolean | `false` | Explicitly allow a failed live provider to return synthetic output in development/test only. Keep disabled for real research; production rejects it. |
| `INTELX_DB_URL` | String | `sqlite+aiosqlite:///./data/intelx.db` | Async database connection string (SQLite or PostgreSQL). |
| `INTELX_DATA_DIR` | String | `./data` | Local directory for raw file storage and exported report artifacts. |
| `INTELX_API_KEY` | String | Empty | Main service API key; required in production, at least 32 characters, unique from the session secret. |
| `INTELX_API_KEYS` | Comma-separated string or JSON array | Empty | Additional API key values to seed (not a role map). Keys are stored as SHA-256 hashes; roles follow the application seeding policy. |
| `INTELX_SECRET_KEY` | String | Empty | HMAC signing secret for web sessions; required in production, at least 32 characters, and unique from API keys. |
| `INTELX_LLM_PROVIDER` | String | `inference` | LLM backend (`inference`, `ai_universe`, `openai_compatible`, or `anthropic`). |
| `INTELX_LLM_MODEL` | String | `mock-gpt-4o` | Model identifier. Production must set a non-mock model supported by the chosen provider. |
| `INTELX_INFERENCE_URL` | String | `https://inference-h7bn.onrender.com` | Inference/AI-Universe endpoint; override for a private or self-hosted gateway. |
| `INTELX_INFERENCE_API_KEY` | String | Empty | Inference/AI-Universe credential; required when that provider is used in production. |
| `INTELX_LLM_API_KEY` | String | Empty | Generic LLM credential fallback when no matching provider-specific key is set. |
| `INTELX_OPENAI_API_KEY` / `OPENAI_API_KEY` | String | Empty | OpenAI-compatible provider credential; takes precedence over the generic LLM key for those providers. |
| `INTELX_ANTHROPIC_API_KEY` / `ANTHROPIC_API_KEY` | String | Empty | Anthropic provider credential; takes precedence over the generic LLM key for Anthropic. |
| `INTELX_RUN_EMBEDDED_WORKER` | Boolean | Environment-dependent | Run a worker in the API process. Defaults on outside production; production deployments with a separate worker should leave it disabled. |
| `INTELX_MAX_CONCURRENT_RUNS` | Integer | `5` | Maximum concurrent research runs. |
| `INTELX_RETENTION_DAYS_RAW_DOCS` | Integer | `30` | Retention period for raw ingested documents. |
| `INTELX_RETENTION_DAYS_REPORTS` | Integer | `365` | Retention period for completed reports and findings. |
| `OPENAI_BASE_URL` | String | *Optional* | Custom base URL for OpenAI-compatible endpoints (e.g. vLLM or Ollama). |
| `TAVILY_API_KEY` | String | *Optional* | API key for external web search discovery. |

---

## 2. Model Provider Setup

### 1. Offline Mock Mode (Zero-Config Default)
No API keys required. INTELX initializes with local heuristic generators:
```bash
export INTELX_MOCK_MODE=true
```

When `INTELX_MOCK_MODE=false`, upstream-provider failure is surfaced as a failed run instead of silently fabricating a mock answer. A live search that returns no sources while one or more providers fail is also a provider error—not a verified no-evidence result; healthy providers may still contribute partial results, with failures recorded as degradations. `INTELX_ALLOW_MOCK_FALLBACK=true` is an explicit development/test-only escape hatch; production refuses it.

Ecosystem exports are evidence-gated: Futuris context uses only recent, completed, answered runs; exogenous signals use only active claims with confidence of at least 0.70, while disputed or unverified findings retain their status. Sector queries do not widen to unrelated sectors. StrateX market responses include source references when available, return neutral `INSUFFICIENT_EVIDENCE` output for a successful empty search, and report HTTP 503 when live search fails without local evidence. Generic market baselines are not fabricated.

### 2. Inference / AI-Universe
Production deployments using the default gateway need an upstream model ID and inference-service credential:
```bash
export INTELX_MOCK_MODE=false
export INTELX_LLM_PROVIDER=inference
export INTELX_LLM_MODEL="<model-id-supported-by-the-inference-service>"
export INTELX_INFERENCE_API_KEY="<inference-service-key>"
```

### 3. OpenAI / Compatible Inference (vLLM, Ollama, DeepSeek)
```bash
export INTELX_MOCK_MODE=false
export INTELX_LLM_PROVIDER=openai_compatible
export INTELX_LLM_MODEL="<model-id-supported-by-your-endpoint>"
export OPENAI_API_KEY="sk-..."
export OPENAI_BASE_URL="http://localhost:8000/v1"  # Optional private LLM endpoint
```

### 4. Anthropic Claude Inference
```bash
export INTELX_MOCK_MODE=false
export INTELX_LLM_PROVIDER=anthropic
export INTELX_LLM_MODEL="<model-id-supported-by-Anthropic>"
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

---

## 5. Live Provider Diagnostics & Smoke Testing

### Diagnostic LLM Role Gateway Smoke (`intelx smoke-llm`)
Validates connectivity, schema generation, latency, token usage, and cost calculation across all 6 agent roles (`planner`, `extractor`, `verifier`, `analyst`, `synthesizer`, `critic`):
```bash
# In Mock Mode (outputs instant mock confirmation and exits 0)
intelx smoke-llm

# With live keys (e.g. OpenAI or Anthropic)
INTELX_MOCK_MODE=false INTELX_LLM_PROVIDER=openai_compatible OPENAI_API_KEY="sk-..." intelx smoke-llm
```

### Full Live Research Run (`intelx smoke-live`)
Executes an end-to-end live research investigation with live web search (Tavily), HTTP retrieval with snippet fallbacks, verbatim-quote alignment, contradiction detection, and citation validation:
```bash
INTELX_MOCK_MODE=false INTELX_LLM_PROVIDER=openai_compatible OPENAI_API_KEY="sk-..." TAVILY_API_KEY="tvly-..." \
  intelx smoke-live --objective "Assess sodium-ion cathode benchmarks" --max-sources 5 --max-usd 1.50
```
Execution metrics and validation verdicts are written directly to `evals/results-live.json`.
