# INTELX System Architecture

This document describes the architectural layers, execution lifecycle, orchestration state machine, and module layout of the **INTELX** intelligence monolith.

---

## 1. Architectural Layers & Component Flow

```mermaid
flowchart TD
    subgraph Ingress ["1. Ingress & Client Surfaces"]
        WebUI["Server-Rendered Web Workspace (web/routes.py)"]
        RESTAPI["REST API v1 (api/v1/endpoints.py)"]
        CLI["IntelX CLI (cli/main.py)"]
    end

    subgraph Governance ["2. Security & Policy Boundary"]
        AuthMiddleware["Bearer Auth & Session HMAC (core/auth.py, web/auth.py)"]
        RateLimiter["Sliding-Window Rate Limiter (core/auth.py)"]
        PolicyEngine["Policy Engine & Audit Logger (core/policy.py)"]
        LogScrubber["Global Secret Scrubber (core/security.py)"]
    end

    subgraph Orchestration ["3. Orchestration & Agent DAG"]
        Engine["Orchestration Engine (orchestration/engine.py)"]
        Worker["Background Worker Daemon (orchestration/worker.py)"]
        EventStream["Live SSE Pub/Sub (orchestration/events.py)"]
        
        subgraph Agents ["Typed Agent Fleet (agents/)"]
            Planner["PlannerAgent (planner.py)"]
            Scout["ScoutAgent (scout.py)"]
            Retriever["RetrieverAgent (retriever.py)"]
            Extractor["ExtractorAgent (extractor.py)"]
            Verifier["VerifierAgent (verifier.py)"]
            Analyst["AnalystAgent (analyst.py)"]
            Critic["CriticAgent (critic.py)"]
            Synthesizer["SynthesizerAgent (synthesizer.py)"]
        end
    end

    subgraph TrustAndMemory ["4. Trust Layer & Memory"]
        Gateway["Role-Routed Model Gateway (models/gateway.py)"]
        Independence["3-Gram Jaccard Independence (core/independence.py)"]
        Confidence["Composite Confidence v1 (core/confidence.py)"]
        EntityResolver["Entity Graph & Alias Index (memory/entities.py)"]
        Artifacts["Multi-Format Exporter (memory/artifacts.py)"]
    end

    subgraph Ingestion ["5. Hardened Ingestion & Storage"]
        SSRF["SSRF & MIME Guard (connectors/web.py)"]
        Sanitizer["Injection Scanner (connectors/sanitize.py)"]
        Normalizer["Character Offset Normalizer (memory/normalize.py)"]
        SecretRedactor["Offset-Preserving Redactor (core/security.py)"]
        DB[(SQLite WAL / PostgreSQL)]
        RawFiles[("data/raw Storage")]
    end

    Ingress --> Governance
    Governance --> Engine
    Engine --> Worker
    Worker --> Agents
    Agents --> Gateway
    Agents --> Independence
    Agents --> Confidence
    Agents --> EntityResolver
    Worker --> Ingestion
    Ingestion --> DB
    Ingestion --> RawFiles
    Worker --> Artifacts
    Engine --> EventStream
```

---

## 2. Research Job State Machine

All investigations follow strict transition rules enforced in [`intelx/orchestration/engine.py`](file:///d:/IntelX/intelx/orchestration/engine.py). Any invalid state transition raises an `InvalidStateTransitionError`.

```mermaid
stateDiagram-v2
    [*] --> QUEUED: Job Created
    QUEUED --> PLANNING: Worker Claim
    PLANNING --> DISCOVERING: Subquestions Decomposed
    DISCOVERING --> RETRIEVING: Search Queries Dispatched
    RETRIEVING --> EXTRACTING: Documents Downloaded & Normalized
    EXTRACTING --> VERIFYING: Primary Verbatim Spans Extracted
    VERIFYING --> ANALYZING: Corroboration & Independence Evaluated
    ANALYZING --> SYNTHESIZING: Timeline & Graph Structured
    
    ANALYZING --> DISCOVERING: Critic Replan Loop (Max 1)
    
    SYNTHESIZING --> REVIEW_REQUIRED: Contradictions / Review Gate
    REVIEW_REQUIRED --> SYNTHESIZING: Human Approved
    
    SYNTHESIZING --> COMPLETED: Artifacts Generated
    
    QUEUED --> CANCELLED: User Cancellation
    PLANNING --> CANCELLED
    DISCOVERING --> CANCELLED
    RETRIEVING --> CANCELLED
    EXTRACTING --> CANCELLED
    VERIFYING --> CANCELLED
    ANALYZING --> CANCELLED
    SYNTHESIZING --> CANCELLED
    
    PLANNING --> FAILED: Unrecoverable Error
    DISCOVERING --> FAILED
    RETRIEVING --> FAILED
    EXTRACTING --> FAILED
    VERIFYING --> FAILED
    ANALYZING --> FAILED
    SYNTHESIZING --> FAILED
    
    COMPLETED --> [*]
    CANCELLED --> [*]
    FAILED --> [*]
```

---

## 3. Module & Package Layout

```
intelx/
├── agents/             # Typed agent implementations with Pydantic contracts
│   ├── base.py         # Agent ABC and AgentRegistry
│   ├── planner.py      # Objective decomposition & strategy allocation
│   ├── scout.py        # Search query execution & candidate deduplication
│   ├── retriever.py    # Fetching & normalization coordinator
│   ├── extractor.py    # Verbatim span claim extraction
│   ├── verifier.py     # Independent corroboration & contradiction detection
│   ├── analyst.py      # Timeline derivation & entity relationship mapping
│   ├── critic.py       # Self-critique, replanning, and review gating
│   └── synthesizer.py  # Report generation & groundedness partition
├── api/v1/             # REST endpoints (15 operations) & OpenAPI schema
├── app/                # FastAPI application factory, lifespan, and middlewares
├── cli/                # Standalone console command line interface
├── connectors/         # External search, HTTP fetching, SSRF guards, injection scanner
├── core/               # Settings, auth, policy engine, errors, logging, security, retention
├── db/                 # Models (18 tables), async engine, sessionmaker, Alembic migrations, repos
├── memory/             # Normalization, entities, and atomic multi-format artifacts
├── models/             # Model gateway, cost meters, and provider adapters (Mock, OpenAI, Anthropic)
└── web/                # Server-rendered Jinja2 UI, static CSS/JS, and citation inspection drawer
```
