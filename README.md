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
  ├── core/            # Settings, errors, structured JSON logging, version
  ├── domain/          # Entities, enums, value objects, and shared schemas
  ├── db/              # Async SQLAlchemy engine, sessionmaker, Alembic migrations
  ├── api/             # HTTP API routers (v1 endpoints, health/readiness)
  ├── agents/          # Specialized role agents (Planner, Extractor, Synthesizer, etc.)
  ├── connectors/      # Search providers, LLM adapters, web crawlers
  ├── orchestration/   # Research execution engine and budget tracking
  ├── memory/          # Scratchpad, claim graphs, and working state
  ├── web/             # Web UI templates and interactive report viewers
  └── data/            # Local data directory (db, raw cache, artifacts)
```

---

## 📖 Engineering Diary

INTELX maintains a strict engineering diary tracking all design decisions, architectural additions, bug resolutions, and testing invariants.

- 🗂️ **Master Diary Index**: [INTELX_DIARY.md](INTELX_DIARY.md)
- 📅 **Daily Logs**: Located in [`diary/`](diary/)
- 🧪 **Diary Validator**: Run `python scripts/verify_diary.py` to verify invariant compliance ($50 < \text{lines} < 100$, $15 < \text{summary bullets} < 30$).

---

## 🧪 Testing & Linting

```bash
make test    # Run pytest test suite
make lint    # Check formatting and lint rules via ruff
```
