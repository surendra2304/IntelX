# 🔍 IntelX — Live Intelligence & OSINT Synthesis Engine

[![IntelX CI](https://github.com/surendra2304/IntelX/actions/workflows/ci.yml/badge.svg)](https://github.com/surendra2304/IntelX/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![SQLite 3 WAL](https://img.shields.io/badge/SQLite_3-WAL_Mode-003B57.svg)](https://www.sqlite.org/wal.html)

**IntelX** is the dedicated live intelligence gathering, search indexing, rate-limited web scraping, and OSINT knowledge synthesis specialist of the **FRIDAY Universe**.

It decomposes complex investigative objectives into targeted queries, crawls and scrapes external web assets while respecting robots.txt and SSRF defenses, indexes claims and evidence in local SQLite 3 WAL storage, cross-checks facts across multiple independent sources, resolves contradictions, and delivers machine-verified intelligence reports.

---

## 🏛️ Ecosystem Topology & Ground Truth

IntelX operates as a containerized microservice deployed to **Oracle Cloud Always Free** under the private Docker network mesh (`friday_mesh`), routed through **Caddy** and the **FRIDAY Core** gateway.

| Attribute | Deployment Ground Truth |
| :--- | :--- |
| **Identity** | `intelx` (Specialist Agent) |
| **Public Gateway URL** | `https://friday-universe.duckdns.org/intelx` |
| **Container Mesh URL** | `http://intelx:8000` |
| **Internal Container Port** | `8000` |
| **Host Port Mapping** | `8005` (`8005:8000`) |
| **Gateway Proxy** | FRIDAY Core (`http://friday:10000`) / Caddy HTTPS |
| **Database Engine** | Local SQLite 3 with WAL Mode (`./data/intelx.db`) |
| **Container Network** | `friday_mesh` |

---

## 🚀 Key Capabilities

1. **Live Search Indexing**: Multi-engine search capability over local knowledge bases and live web providers (Tavily, Wikipedia, DuckDuckGo).
2. **Hardened Web Scraping**: Rate-limited, asynchronous HTML and PDF extraction featuring SSRF socket-level protection, content sanitization, and robots.txt politeness.
3. **Verbatim Evidence Extraction**: Immutable provenance chains down to character offsets:
   $$\text{Finding} \longrightarrow \text{Claim} \longrightarrow \text{Evidence (Verbatim Span)} \longrightarrow \text{Document} \longrightarrow \text{Source}$$
4. **Contradiction Resolution**: Automated detection of conflicting numerical data, temporal changes, and disputed facts with reciprocal links.
5. **OSINT Synthesis**: Generation of structured intelligence briefs, spoken executive briefs, and multi-format exports (Markdown, JSON, CSV).

---

## 📡 API Specification & Curl Reference

All requests accept JSON and require an Authorization header in production: `Authorization: Bearer <INTELX_API_KEY>`.

### 1. Health & Liveness Probe (`GET /healthz`)
Verifies process health and database connectivity.

```bash
curl -X GET "https://friday-universe.duckdns.org/intelx/healthz"
```

**Response (`200 OK`):**
```json
{
  "status": "ok",
  "service": "intelx",
  "evidence_class": "process_liveness",
  "observed_at": "2026-10-14T21:00:00.000000Z",
  "version": "2.0.0",
  "mock_mode": false,
  "database": "ok",
  "timestamp": "2026-10-14T21:00:00.000000Z"
}
```

### 2. Search Indexing (`POST /search`)
Executes full-text keyword and semantic discovery across indexed sources and live web feeds.

```bash
curl -X POST "https://friday-universe.duckdns.org/intelx/search" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer dev-admin-key" \
  -d '{
    "query": "solid-state battery energy density",
    "limit": 5
  }'
```

**Response (`200 OK`):**
```json
{
  "status": "ok",
  "query": "solid-state battery energy density",
  "total_results": 2,
  "results": [
    {
      "id": "src_8f9c12",
      "title": "Solid-State Electrolyte Breakthroughs 2026",
      "url": "https://example.com/energy/solid-state",
      "publisher": "Energy Tech Review",
      "trust_tier": "verified"
    }
  ]
}
```

### 3. Rate-Limited Scraping (`POST /scrape`)
Safely extracts readable text content from an external web page with strict SSRF socket validation, robots.txt compliance, and size caps.

```bash
curl -X POST "https://friday-universe.duckdns.org/intelx/scrape" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer dev-admin-key" \
  -d '{
    "url": "https://en.wikipedia.org/wiki/Artificial_intelligence",
    "max_bytes": 1000000
  }'
```

**Response (`200 OK`):**
```json
{
  "status": "ok",
  "url": "https://en.wikipedia.org/wiki/Artificial_intelligence",
  "title": "Artificial intelligence - Wikipedia",
  "content_length": 48201,
  "text": "Artificial intelligence (AI) is the intelligence of machines or software...",
  "status_code": 200
}
```

### 4. OSINT Synthesis & Summarization (`POST /summarize`)
Extracts verifiable claims, propositions, and synthesized findings from raw text or knowledge base queries.

```bash
curl -X POST "https://friday-universe.duckdns.org/intelx/summarize" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer dev-admin-key" \
  -d '{
    "text": "GigaWatt Labs achieved 520 Wh/kg in solid-state cell testing during Q3 2026.",
    "max_length": 200
  }'
```

**Response (`200 OK`):**
```json
{
  "status": "ok",
  "summary": "GigaWatt Labs achieved 520 Wh/kg in solid-state cell testing during Q3 2026.",
  "evidence_claims": [],
  "confidence": 0.85
}
```

---

## 🗄️ Database Architecture (SQLite 3 WAL)

IntelX leverages **SQLite 3** running in **Write-Ahead Logging (WAL)** mode for low latency, zero external database overhead, and resilient concurrent reads:

- **Storage Location**: `./data/intelx.db`
- **WAL Journaling**: `PRAGMA journal_mode = WAL;` (enables non-blocking reads alongside single writes).
- **Busy Timeout**: `PRAGMA busy_timeout = 5000;` (prevents indefinite locking).
- **Integrity**: `PRAGMA synchronous = NORMAL;` and `PRAGMA foreign_keys = ON;`.
- **Full-Text Search (FTS5)**: Integrated virtual tables (`chunks_fts`, `claims_fts`) with automatic trigger synchronization.

---

## ⚙️ Environment Variables Reference

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `PORT` | Integer | `8000` | Internal HTTP container binding port. |
| `INTELX_ENV` | String | `production` | Deployment mode: `development`, `staging`, `production`. |
| `INTELX_MOCK_MODE` | Boolean | `false` | When true, mock generators simulate research. Must be `false` in production. |
| `INTELX_DB_URL` | String | Required in production | Oracle Autonomous Database DSN. PostgreSQL and SQLite are not supported production backends. |
| `INTELX_DATA_DIR` | String | `./data` | File storage path for artifacts, raw files, and uploads. |
| `INTELX_SECRET_KEY` | String | *(Required)* | HMAC signing key for sessions and cryptographic audits. |
| `INTELX_API_KEY` | String | *(Required)* | Bearer authentication key for IntelX REST endpoints. |
| `INTELX_API_KEYS` | String | *(Optional)* | Comma-separated secondary authorized API keys. |
| `INTELX_CORS_ORIGINS` | JSON List | `["https://friday-universe.duckdns.org", ...]` | CORS allowed origin domains. |
| `INTELX_LLM_PROVIDER` | String | `inference` | Active provider: `inference`, `openai_compatible`, `anthropic`, `mock`. |
| `INTELX_INFERENCE_URL` | String | `http://inference:8000` | Internal mesh URL to Inference gateway. |
| `INTELX_INFERENCE_API_KEY` | String | *(Optional)* | Secret key for Inference gateway access. |
| `INTELX_MEMORA_URL` | String | `http://memora:8000` | Internal mesh URL for Memora persistent memory. |
| `INTELX_FUTURIS_BASE_URL` | String | `http://futuris:8000` | Internal mesh URL for Futuris predictive engine. |
| `INTELX_STRATEX_BASE_URL` | String | `http://stratex:8000` | Internal mesh URL for StrateX trading platform. |
| `INTELX_FRIDAY_URL` | String | `http://friday:10000` | Gateway URL for FRIDAY central control. |
| `INTELX_RUN_EMBEDDED_WORKER` | Boolean | `true` | Runs the orchestration worker in-process inside the FastAPI event loop. |
| `INTELX_MAX_CONCURRENT_RUNS` | Integer | `5` | Maximum active concurrent research runs. |

---

## 🐳 Quickstart & Local Verification

### Running with Docker Compose
```bash
# 1. Start IntelX on the friday_mesh container network
docker compose up -d

# 2. Check container liveness
curl -f http://localhost:8005/healthz
```

### Local Development
```bash
# 1. Activate Python 3.11 virtual environment
.\.venv\Scripts\Activate.ps1   # Windows
source .venv/bin/activate      # Linux / macOS

# 2. Install dependencies
pip install -r requirements.txt
pip install -e ".[dev]"

# 3. Run test suite
pytest -q
```
