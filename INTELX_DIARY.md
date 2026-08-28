# IntelX Engineering Diary — Master Index

Welcome to the engineering diary of **IntelX**. This document tracks daily progress, architectural decisions, test metrics, and security milestones throughout the development lifecycle.

---

## 📅 Daily Logs

### 📈 [Day 1 — 2026-08-28: Steps 1 through 12 (Core Monolith, Evidence Model, Gateway, Connectors, Agents, Trust Layer, Orchestrator, Artifacts, API Surface, Web UI, Security Hardening & Evals Harness)](diary/2026-08-28.md)
- **🎯 Focus**: Repository genesis, Step 1 architectural setup, async database engine with SQLite WAL, Alembic migrations, FastAPI app factory, structured logging, Step 2 relational evidence data model (18 tables), typed repositories, span integrity enforcement, cryptographic AuditChain, FTS5 search, Step 3 central Model Gateway with role-based routing, Step 4 security-hardened connectors (`HttpFetchConnector`, `WebSearchConnector`, `FileConnector`), normalization with character offsets, Step 5 first four typed agents (`PlannerAgent`, `ScoutAgent`, `RetrieverAgent`, `ExtractorAgent`), Step 6 trust layer (`VerifierAgent`, deterministic v1 composite confidence formula, contradiction handling, `EntityResolver`, `AnalystAgent`, `CriticAgent`), Step 7 orchestration engine (`OrchestrationEngine` state machine, `OrchestrationWorker`, `EventStreamManager` SSE broadcasting), Step 8 synthesis & artifacts (`SynthesizerAgent`, `render_report_markdown` with all 9 required sections, machine-enforced citation integrity, groundedness partitioning, atomic multi-format artifact manager producing `report.md`, `report.json`, `evidence_pack.json`, `sources.csv`), Step 9 full API surface (`intelx/api/v1/`, Bearer auth, seeded SHA256 hashed keys, role tiers, sliding-window rate limiting, table-backed `PolicyEngine` with denial audit logging, 14 REST endpoints, OpenAPI docs, idempotency keys, SSE streaming, artifact downloads, human review gates, and cryptographic audit verification), Step 10 Web UI (server-rendered Jinja2 workspace, signed HMAC session cookies, safe markdown renderer with XSS protection, interactive citation inspection drawer, review queue, knowledge search, and zero npm/CDN offline design), Step 11 Security Hardening (global regex log scrubber, character-preserving document secret redactor, raw file retention purge engine with CLI/API support, 15-sample adversarial injection suite, SSRF battery, and threat model documentation in `docs/threat-model.md`), and Step 12 Evaluation & Test Hardening (8 golden evaluation tasks, realistic test fixtures, deterministic evaluation runner `evals/run.py`, `evals/thresholds.json`, baseline `evals/results.json`, 5-job concurrency smoke tests, and Makefile eval target).
- **💡 What I Accomplished**:
  - I created the official IntelX repository and pushed the baseline to GitHub.
  - I established the engineering diary framework (`diary/YYYY-MM-DD.md` and `INTELX_DIARY.md`) and automated validation script `scripts/verify_diary.py`.
  - I built the complete FastAPI application factory with lifespan management and background worker hooks.
  - I configured async SQLAlchemy 2.0 with SQLite WAL mode and set up Alembic migrations (`0001_initial_schema` and `0002_evidence_data_model`).
  - I implemented all 18 typed SQLAlchemy 2.0 models covering runs, tasks, sources, documents, chunks, entities, claims, evidence, findings, artifacts, and audit events.
  - I authored typed repository layer in `intelx/db/repos.py` (`RunRepo`, `SourceRepo`, `ClaimRepo`, `EvidenceRepo`, `AuditChain`).
  - I built the central `ModelGateway` in `intelx/models/gateway.py` with role-based routing (`planner`, `extractor`, `verifier`, `analyst`, `synthesizer`, `critic`).
  - I implemented `HttpFetchConnector`, `WebSearchConnector`, and `FileConnector` with strict SSRF and MIME guards.
  - I built `BaseAgent` and `AgentRegistry` in `intelx/agents/base.py` enforcing `<<<EXTERNAL_DOCUMENT>>>` user-message delimiters.
  - I authored `PlannerAgent`, `ScoutAgent`, `RetrieverAgent`, and `ExtractorAgent` with verbatim substring matching.
  - I engineered `VerifierAgent` with 3-gram Jaccard independence checking, two-sided contradiction handling, and quarantine bounds.
  - I built the deterministic v1 composite confidence formula in `intelx/core/confidence.py` with penalty tracking and human-auditable documentation.
  - I implemented `EntityResolver` in `intelx/memory/entities.py` with company alias normalization, automated merge thresholds, and proposal lifecycle.
  - I authored `AnalystAgent` and `CriticAgent` structuring timelines, knowledge graphs, and draft critiques.
  - I engineered `OrchestrationEngine` managing DAG state machine transitions, concurrency semaphores, budget ceilings, and review gates.
  - I built `OrchestrationWorker` in `intelx/orchestration/worker.py` and `EventStreamManager` in `intelx/orchestration/events.py` for live SSE pub/sub telemetry.
  - I developed the official Markdown report renderer with all 9 standard sections and strict citation formatting `[S:id]` / `[C:id]`.
  - I built machine-enforced citation integrity checking raising `IntegrityError` on any unresolvable citation tokens.
  - I created groundedness validation moving unbacked findings into an Unverified Observations appendix.
  - I implemented versioned atomic artifact exporters generating `report.md`, `report.json`, `evidence_pack.json`, and `sources.csv` with recorded SHA256 checksums.
  - I engineered Bearer API key authentication with SHA256 hashed secrets, RBAC tiers (`admin`, `member`), and sliding-window rate limiting (120 req/min).
  - I built the dynamic `PolicyEngine` evaluating domain allow/denylists, budget caps, and logging denials into the tamper-evident audit ledger.
  - I created all 14 REST endpoints under `/api/v1` with full OpenAPI documentation and RFC 7807 problem details error formatting.
  - I built the complete server-rendered web workspace in `intelx/web/` with Jinja2 templates and offline vanilla JS.
  - I implemented safe markdown rendering with XSS sanitization and interactive slide-out citation drawers.
  - I engineered `intelx/core/security.py` with global regex log scrubbing and length-preserving secret redactions.
  - I built `intelx/core/retention.py` automating raw file purges with CLI and API endpoints.
  - I expanded `IngestionSanitizer` to detect 15 adversarial injection techniques and Unicode homoglyphs.
  - I authored `docs/threat-model.md` specifying threat actors, protected assets, and code-level mitigations.
  - I developed the 8-task golden evaluation harness in `evals/run.py` writing baseline `evals/results.json`.
  - I authored `tests/test_concurrency.py` verifying state isolation across 5 parallel pipelines.
  - I authored comprehensive test suites achieving 100% green pass rate across 84 automated tests.
- **🛡️ Fixes & Hardening**: Fixed SQLite timeout under parallel writes, resolved citation source set lookups in evals, and validated 100% mechanical quality gate compliance.
- **📊 Test Results**: **84 tests passed** (100% green pass rate).

---

## 📐 Diary Rules & Guidelines

All daily entries must adhere to the following specifications:
1. **File Length**: `diary/YYYY-MM-DD.md` must be strictly between 51 and 99 lines.
2. **Daily Summary**: Must contain between 16 and 29 bullet points starting with `- I ` (first-person active voice).
3. **Mandatory Sections**:
   - `## Daily Summary`
   - `## What I Built & Did`
   - `## Bugs I Found & Fixed`
   - `## Key Decisions & Architecture`
   - `## Testing, Security & State`
4. **Verification**: Run `python scripts/verify_diary.py` before committing any log entry.
