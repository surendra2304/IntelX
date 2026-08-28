# Changelog

All notable changes to the **INTELX** intelligence research platform will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1.0] - 2026-08-28

### Initial Standalone Release

#### Core & Architecture
- **Modular Monolith**: Standalone Python 3.11 architecture with async FastAPI application factory and lifetime hooks.
- **Relational Evidence Data Model**: 18 typed SQLAlchemy 2.0 models with SQLite WAL mode and PostgreSQL compatibility.
- **Span Integrity Invariant**: Mandatory exact substring assertion `document.text[span_start:span_end] == quote` preventing citation hallucinations.
- **Cryptographic Audit Ledger**: Monotonic append-only SHA-256 hash chaining verifying system action provenance.
- **Model Gateway**: Centralized LLM router with role-based routing (`planner`, `extractor`, `verifier`, `analyst`, `synthesizer`, `critic`) and offline MockProvider.

#### Connectors & Security
- **Hardened Ingestion**: `HttpFetchConnector`, `WebSearchConnector`, and `FileConnector` supporting PDF, DOCX, HTML, Markdown, CSV, and JSON parsing.
- **SSRF Defense Layer**: DNS resolution checks intercepting localhost, private subnets (RFC 1918), and cloud metadata endpoints.
- **Adversarial Ingestion Defense**: 15-pattern injection scanner and Unicode homoglyph normalizer flagging risks to sidecars without mutating raw sources.
- **Zero-Telemetry Log Scrubber**: Global root logger filter stripping bearer tokens, API keys, and credentials from all logs and traces.
- **Character-Preserving Secret Redactor**: Length-preserving redaction maintaining 100% citation span offset accuracy.
- **Raw File Retention Engine**: CLI and API endpoints automatically purging unreferenced raw HTML/PDF files after configured retention periods.

#### Agent Fleet & Trust Layer
- **8 Specialized Typed Agents**:
  - `PlannerAgent`: Subquestion decomposition and source budget allocation.
  - `ScoutAgent`: Discovery query formulation and candidate deduplication.
  - `RetrieverAgent`: Multiprocess fetching, SSRF checks, and normalization.
  - `ExtractorAgent`: Verbatim substring extraction with entity recognition.
  - `VerifierAgent`: 3-gram Jaccard independence checking and contradiction detection.
  - `AnalystAgent`: Timeline ordering and entity relationship mapping.
  - `CriticAgent`: Quality review gating and single-loop replanning.
  - `SynthesizerAgent`: Report drafting, direct answers, and groundedness partitioning.
- **Composite Confidence Formula v1**: Mathematical scoring ledger combining base tiers, corroboration boosts, and penalty deductions.
- **Entity Resolution Graph**: Canonical alias dictionary, automated merge thresholds, and proposal lifecycles.

#### Orchestration & Telemetry
- **Deterministic DAG State Machine**: Strict status transitions (`QUEUED`, `PLANNING`, `DISCOVERING`, `RETRIEVING`, `EXTRACTING`, `VERIFYING`, `ANALYZING`, `SYNTHESIZING`, `COMPLETED`, `REVIEW_REQUIRED`, `FAILED`, `CANCELLED`).
- **Live SSE Event Stream**: Server-Sent Events broadcasting real-time progress updates.
- **Atomic Multi-Format Artifacts**: Exporters generating `report.md`, `report.json`, `evidence_pack.json`, and `sources.csv` with SHA-256 integrity digests.

#### User Interfaces & API Surface
- **Versioned REST API (v1)**: 15 OpenAPI endpoints with Bearer key auth, SHA-256 hashed secrets, sliding-window rate limiting, and RFC 7807 error responses.
- **Offline Server-Rendered Web UI**: Jinja2 templates, vanilla JS, custom CSS, signed HMAC cookies, and slide-out citation inspection drawer.
- **Unified CLI (`intelx`)**: Console commands for `serve`, `worker`, `migrate`, `seed-demo`, `eval`, `purge`, and `verify-audit`.

#### Evaluation & Quality Gates
- **Golden Benchmark Harness**: 8 evaluation tasks evaluating citation validity (100%), groundedness (100%), contradiction recall (100%), and null result correctness (100%).
- **Automated Test Battery**: 84 unit, integration, adversarial, and concurrency smoke tests achieving 100% green pass rate.
- **Containerization**: Multi-stage unprivileged `Dockerfile` and `docker-compose.yml`.
