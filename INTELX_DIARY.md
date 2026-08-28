# IntelX Engineering Diary — Master Index

Welcome to the engineering diary of **IntelX**. This document tracks daily progress, architectural decisions, test metrics, and security milestones throughout the development lifecycle.

---

## 📅 Daily Logs

### 📈 [Day 1 — 2026-08-28: Steps 1, 2, 3, 4 & 5 Core, Evidence Model, Gateway, Connectors & Agents](diary/2026-08-28.md)
- **🎯 Focus**: Repository genesis, Step 1 architectural setup, async database engine with SQLite WAL, Alembic baseline, FastAPI app factory, request-ID middleware, structured JSON logging, Step 2 relational evidence data model (18 tables), typed repositories, span integrity enforcement, cryptographic AuditChain, FTS5 search, Step 3 central Model Gateway with role-based routing and structured output self-correction, Step 4 security-hardened connectors (`HttpFetchConnector` with multi-hop SSRF/robots guards, `WebSearchConnector`, `FileConnector`), normalization with absolute character offsets, Step 5 first four typed agents (`PlannerAgent`, `ScoutAgent`, `RetrieverAgent`, `ExtractorAgent`) with hard post-return span validation and opinion attribution checks.
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
  - I authored `PlannerAgent` in `intelx/agents/planner.py` with 5-subquestion capping and budget allocation.
  - I created `ScoutAgent` in `intelx/agents/scout.py` querying web search and existing internal FTS5 knowledge.
  - I built `RetrieverAgent` in `intelx/agents/retriever.py` with transient retry tolerance and logical error capture.
  - I developed `ExtractorAgent` in `intelx/agents/extractor.py` enforcing verbatim substring matching, absolute span recalculation, and opinion attribution rules.
  - I developed comprehensive test suites with 35 passing tests and verified zero ruff lint errors.
- **🛡️ Fixes & Hardening**: Fixed test session rollback with valid foreign key run references, maintained mock schema backwards compatibility, and enforced rejection of unverifiable claims.
- **📊 Test Results**: **35 tests passed** (100% green pass rate).

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
