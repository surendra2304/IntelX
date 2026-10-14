# 🏛️ SYSTEM MANIFEST — IntelX Evidence & Intelligence Engine

> **Official Subsystem Name:** IntelX  
> **Role in Ecosystem:** Live Intelligence Gathering, Search Indexing, Web Scraping & Knowledge Synthesis Specialist  
> **Repository:** [surendra2304/IntelX](https://github.com/surendra2304/IntelX) (Branch: main)  
> **Workspace Path:** d:\FRIDAY Universe\IntelX  

---

## ☁️ 1. Deployment & Topology (Oracle Cloud Always Free)

| Attribute | Deployment Ground Truth |
| :--- | :--- |
| **Public Gateway URL** | [https://friday-universe.duckdns.org/intelx](https://friday-universe.duckdns.org/intelx) |
| **Health Check Endpoint** | https://friday-universe.duckdns.org/intelx/healthz |
| **Internal Container Port** | `8000` |
| **Host Port Mapping** | `8005` (`8005:8000`) |
| **Docker Mesh Network** | `friday_mesh` (`http://intelx:8000`) |
| **Gateway Routing** | FRIDAY Core at `http://friday:10000` via Caddy reverse proxy |
| **Database Topology** | Local SQLite 3 with WAL Mode (`intelx.db`) |
| **Authentication Header** | `Authorization: Bearer <INTELX_API_KEY>` |

---

## 🎯 2. Purpose & Responsibilities

### What IntelX IS:
* IntelX is an evidence-driven research, web scraping, and fact-extraction platform. It ingests multi-source web documents, extracts verbatim proposition spans, tracks mathematical confidence ledgers, resolves contradictions, and publishes verified executive reports.

### What IntelX DOES:
* Operates as the **Live Intelligence Gathering, Search Indexing, Web Scraping & Knowledge Synthesis Specialist** within the 9-agent FRIDAY Universe.
* Communicates directly with peer agents across the private `friday_mesh` container network.
* Persists private long-term memory records to **Memora** under `memora://intelx/private`.

---

## 🌐 3. Ecosystem Endpoint Configuration (`friday_mesh`)

Within the container mesh and via public gateway routing:

```env
# ============================================================================== #
#               FRIDAY UNIVERSE MASTER ECOSYSTEM CONFIGURATION                  #
# ============================================================================== #

# 1. ⚡ Inference AI Multi-Model Gateway
INFERENCE_URL=http://inference:8000
# Public: https://friday-universe.duckdns.org/inference

# 2. 🧠 Memora Persistent Long-Term Memory
MEMORA_URL=http://memora:8000
# Public: https://friday-universe.duckdns.org/memora

# 3. 📈 StrateX Algorithmic Trading Platform
STRATEX_URL=http://stratex:8000
# Public: https://friday-universe.duckdns.org/stratex

# 4. 🔍 IntelX Live Intelligence & Scraping Engine
INTELX_URL=http://intelx:8000
# Public: https://friday-universe.duckdns.org/intelx

# 5. 🔮 Futuris Predictive Forecasting Engine
FUTURIS_URL=http://futuris:8000
# Public: https://friday-universe.duckdns.org/futuris

# 6. 🌐 Cortex Autonomous Web Operations & Intelligence
CORTEX_URL=http://cortex:8000
# Public: https://friday-universe.duckdns.org/cortex

# 7. 🛠️ Forge Autonomous Software Engineering Engine
FORGE_URL=http://forge:8000
# Public: https://friday-universe.duckdns.org/forge

# 8. 🛡️ Sentinel Cybersecurity & Threat Defense Shield
SENTINEL_URL=http://sentinel:8000
# Public: https://friday-universe.duckdns.org/sentinel

# 9. 🤖 FRIDAY Central Desktop Operating System Gateway
FRIDAY_URL=http://friday:10000
# Public: https://friday-universe.duckdns.org
```

---

## 🤖 4. Repository Guide

When working inside this repository:
* **Identity:** You are working inside **IntelX** (`d:\FRIDAY Universe\IntelX`).
* **Service Topology:** Internal Port `8000`, Host Port `8005`, Gateway Path `/intelx`.
* **Authentication:** Incoming requests require the configured `INTELX_API_KEY`.
* **Zero Mocking In Production:** Real search, web retrieval, and extraction must run genuinely against live sources.
