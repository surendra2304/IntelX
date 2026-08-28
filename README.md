# INTELX

**INTELX** is an evidence-driven intelligence research monolith that decomposes complex research questions into structured subquestions, retrieves and normalizes heterogeneous source documents, extracts atomic propositions with machine-verified verbatim spans, scores claims using a deterministic mathematical confidence ledger, resolves opposing contradictions, and generates fully cited intelligence reports with atomic multi-format exports.

---

## ⚡ Quickstart (Zero External API Keys Needed)

INTELX comes pre-configured with **Mock Mode** by default, allowing you to run full end-to-end research pipelines, web workspace sessions, and automated quality benchmarks out of the box with zero external dependencies:

```bash
# 1. Install dependencies & run database migrations
make setup
make migrate

# 2. Seed realistic evaluation fixture documents & queue a demo job
make seed-demo

# 3. Launch the web workspace & API server
make dev
```

Now navigate to **[http://localhost:8000](http://localhost:8000)** in your browser:
- **Default Seeded Admin Key**: `dev-admin-key`
- **Default Seeded Member Key**: `dev-member-key`

---

## 🐳 Docker Deployment

Run the complete unprivileged multi-stage container environment with persistent data storage:

```bash
# Start INTELX container with persistent volume
docker compose up -d

# Inspect health status
curl -f http://localhost:8000/healthz
```

---

## 📊 Baseline Quality Gate Results (`evals/results.json`)

INTELX enforces mechanical quality gates across 8 golden benchmark tasks (`evals/golden/*.json`) covering contradiction detection, citation resolution, independence heuristics, and prompt injection resistance:

```bash
make eval    # Run deterministic golden evaluation suite
```

| Evaluation Metric | Baseline Score | Quality Gate Threshold | Status | Description |
|---|---|---|---|---|
| **Citation Validity Rate** | **100.0%** | $\ge 100.0\%$ | `PASS` | All `[S:id]` / `[C:id]` citations resolve to valid database entities. |
| **Groundedness Rate** | **100.0%** | $\ge 90.0\%$ | `PASS` | Key report findings backed by $\ge 1$ active primary claim. |
| **Contradiction Recall** | **100.0%** | $\ge 75.0\%$ | `PASS` | Opposing measurement and factual conflicts flagged into Disputed status. |
| **Null Result Correctness** | **100.0%** | $\ge 100.0\%$ | `PASS` | Impossible/zero-evidence objectives yield `INSUFFICIENT_EVIDENCE`. |
| **Independence Correctness** | **100.0%** | $\ge 100.0\%$ | `PASS` | Syndicated wire copies rejected from independent corroboration counts. |
| **Extraction Precision** | **82.3%** | — | `PASS` | Primary assertions matching expected benchmark propositions. |
| **Completion Rate** | **100.0%** | $\ge 100.0\%$ | `PASS` | All golden benchmark investigations run successfully to completion. |

---

## 🏛️ Architecture & Component Flow

```
intelx/
  ├── agents/          # Typed agent fleet (Planner, Scout, Retriever, Extractor, Verifier, Analyst, Critic, Synthesizer)
  ├── api/v1/          # REST API endpoints (15 operations) & OpenAPI schema
  ├── app/             # FastAPI application factory, lifespan management, and security middlewares
  ├── cli/             # Unified console CLI ('intelx serve', 'intelx worker', 'intelx seed-demo', etc.)
  ├── connectors/      # Search providers, HTTP crawlers, SSRF socket defenses, injection scanner
  ├── core/            # Settings, Bearer auth, PolicyEngine, confidence formula v1, secret redactor
  ├── db/              # SQLAlchemy 2.0 models (18 tables), async engine, sessionmaker, Alembic migrations, repos
  ├── memory/          # Offset normalizer, entity resolution graph, atomic multi-format artifact manager
  ├── models/          # Model gateway, role-based LLM routing, and Mock/OpenAI/Anthropic provider adapters
  └── web/             # Server-rendered Jinja2 templates, offline vanilla JS, and citation drawer
```

### The Provenance Chain
Every statement in an INTELX report resolves down a five-level immutable provenance chain:
$$\text{Finding} \longrightarrow \text{Claim} \longrightarrow \text{Evidence (Verbatim Span)} \longrightarrow \text{Document} \longrightarrow \text{Source}$$

Verbatim span matches are enforced at the database level: $\text{document.text}[\text{span\_start} : \text{span\_end}] == \text{quote}$.

---

## 🛠️ CLI Reference (`intelx`)

```bash
intelx serve               # Start FastAPI application server on port 8000
intelx worker              # Start background orchestration execution worker
intelx migrate             # Apply database migrations via Alembic
intelx seed-demo           # Seed local fixture data and queue a demo run
intelx eval                # Run deterministic golden evaluation benchmark suite
intelx purge --days 30     # Run retention purge for stale raw cached files
intelx verify-audit        # Cryptographically verify tamper-evident audit ledger
```

---

## 📚 Documentation Index

- 🏛️ **System Architecture**: [docs/architecture.md](docs/architecture.md)
- 🔗 **Evidence Provenance & Data Model**: [docs/evidence-model.md](docs/evidence-model.md)
- 🧮 **Confidence Scoring Formula**: [docs/confidence-methodology.md](docs/confidence-methodology.md)
- 📡 **REST API Reference & Curl Guide**: [docs/api.md](docs/api.md)
- ⚙️ **Operations & Provider Configuration**: [docs/operations.md](docs/operations.md)
- 🛡️ **Threat Model & Security Hardening**: [docs/threat-model.md](docs/threat-model.md)
- ⚖️ **Legal, Crawling & Ingestion Posture**: [docs/legal-crawling-posture.md](docs/legal-crawling-posture.md)
- 🚀 **Getting Started Walkthrough**: [docs/getting-started.md](docs/getting-started.md)
- 📝 **Architecture Decision Records (ADRs)**: [docs/adr/](docs/adr/)
- 📖 **Engineering Diary Master Index**: [INTELX_DIARY.md](INTELX_DIARY.md)

---

## 🗺️ Roadmap to Production

- [x] **Step 1–12**: Monolith foundations, evidence schema, role routing, agent fleet, trust layer, orchestration, artifacts, API, Web UI, security hardening, and eval harness.
- [x] **Step 13**: Architecture documentation, ADRs, Dockerization, console CLI, and release polish.
- [ ] **Multi-Tenant Partitioning**: Indexed `tenant_id` namespaces and PostgreSQL Row-Level Security (RLS) policies.
- [ ] **Production Search Scale**: Distributed search connectors (Brave Search, Bing Search, Google Serper) with token bucket rate limiters.
- [ ] **Dense Vector Embeddings**: Hybrid sparse (FTS5 BM25) + dense vector (HNSW / pgvector) hybrid reranking.
- [ ] **Continuous Research Subscriptions**: Recurring cron triggers with automated delta diffing on historical claim graphs.

---

## 🧪 Testing & Linting

```bash
make test          # Run full pytest test battery (84 tests)
make eval          # Run golden evaluation benchmark harness
make lint          # Verify formatting and lint rules via ruff
make verify-audit  # Verify cryptographic audit chain integrity
```
