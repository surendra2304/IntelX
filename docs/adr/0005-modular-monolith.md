# ADR 0005: Modular Monolith Architecture (Over Distributed Microservices)

## Status
Accepted

## Context
Research agent workflows involve numerous interdependent sub-steps: discovery, web scraping, span extraction, contradiction verification, graph derivation, report drafting, and SSE telemetry streaming. Splitting these into separate microservices would introduce distributed transaction overhead, network latency, and deployment friction.

## Decision
INTELX is built as a single Python 3.11 **Modular Monolith** containing:
- Ingress (FastAPI web routes & REST endpoints)
- Background Orchestration Engine & Worker Loop
- Typed Agent Fleet (Planner, Scout, Retriever, Extractor, Verifier, Analyst, Critic, Synthesizer)
- Storage & Cryptographic Audit Ledger

Modules communicate via typed Python function calls and shared database state rather than network RPCs.

## Consequences
### Positive
- **Atomic Operations**: Verification, claim extraction, and audit chaining happen within single database transactions.
- **Fast Local Execution**: In Mock Mode and local deployments, tests and evaluation suites execute in seconds.
- **Simplified Deployment**: A single Docker container or Python virtualenv runs the entire system.

### Negative
- Scaling individual agent types independently (e.g. 100 extractor instances vs 1 planner) requires running the whole worker process.
