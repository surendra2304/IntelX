# INTELX

Standalone, evidence-driven research & intelligence platform that turns research questions into evidence-backed, cited, confidence-labeled intelligence reports.

## 🚀 Quickstart

```bash
make setup
make migrate
make dev
# Open http://localhost:8000/docs in your browser
```

> **Note on Mock Mode**: By default, `INTELX_MOCK_MODE=true`. INTELX runs out-of-the-box with local synthetic data generators without requiring external API keys (OpenAI, Anthropic, Tavily).

---

## 🏛️ Architecture & Project Layout

```
intelx/
  ├── app/             # FastAPI application factory, middleware, lifespan
  ├── core/            # Settings, errors, structured JSON logging, security, retention
  ├── domain/          # Entities, enums, value objects, and shared schemas
  ├── db/              # Async SQLAlchemy engine, sessionmaker, Alembic migrations, repos
  ├── api/             # HTTP API routers (v1 endpoints, health/readiness, policy, audit)
  ├── agents/          # Specialized role agents (Planner, Extractor, Synthesizer, etc.)
  ├── connectors/      # Search providers, LLM adapters, web crawlers, SSRF defense
  ├── orchestration/   # Research execution engine, DAG state machine, budget tracking
  ├── memory/          # Scratchpad, claim graphs, normalization, artifacts
  ├── web/             # Web UI templates, static assets, and interactive report viewers
  └── data/            # Local data directory (db, raw cache, artifacts)
```

---

## 📊 Evaluation Harness & Baseline Quality Gates

INTELX uses deterministic mechanical quality gates across 8 golden benchmark tasks (`evals/golden/*.json`) covering contradiction detection, citation integrity, independence heuristic validation, and injection resistance.

```bash
make eval    # Run deterministic golden evaluation harness
```

### Baseline Quality Gate Results (`evals/results.json`)

| Evaluation Metric | Baseline Score | Quality Threshold | Status | Description |
|---|---|---|---|---|
| **Citation Validity Rate** | **100.0%** | $\ge 100.0\%$ | `PASS` | All `[S:id]` / `[C:id]` citations resolve to valid database entities. |
| **Groundedness Rate** | **100.0%** | $\ge 90.0\%$ | `PASS` | Key report findings supported by $\ge 1$ active primary claim. |
| **Contradiction Recall** | **100.0%** | $\ge 75.0\%$ | `PASS` | Opposing measurement and factual conflicts flagged into Disputed status. |
| **Null Result Correctness** | **100.0%** | $\ge 100.0\%$ | `PASS` | Impossible/zero-evidence objectives yield `INSUFFICIENT_EVIDENCE`. |
| **Independence Correctness** | **100.0%** | $\ge 100.0\%$ | `PASS` | Syndicated wire copies rejected from independent corroboration counts. |
| **Extraction Precision** | **82.3%** | — | `PASS` | Primary assertions matching expected benchmark propositions. |
| **Completion Rate** | **100.0%** | $\ge 100.0\%$ | `PASS` | All golden benchmark investigations run successfully to completion. |

---

## 📖 Engineering Diary

INTELX maintains a strict engineering diary tracking all design decisions, architectural additions, bug resolutions, and testing invariants.

- 🗂️ **Master Diary Index**: [INTELX_DIARY.md](INTELX_DIARY.md)
- 📅 **Daily Logs**: Located in [`diary/`](diary/)
- 🧪 **Diary Validator**: Run `python scripts/verify_diary.py` to verify invariant compliance ($50 < \text{lines} < 100$, $15 < \text{summary bullets} < 30$).

---

## 🧪 Testing & Linting

```bash
make test    # Run full pytest test suite (84 tests)
make eval    # Run golden evaluation benchmark suite
make lint    # Check formatting and lint rules via ruff
```
