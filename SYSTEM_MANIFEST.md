# 🏛️ SYSTEM MANIFEST — IntelX Evidence & Intelligence Engine

> **Official Subsystem Name:** IntelX  
> **Role in Ecosystem:** Multi-Source Evidence Research, Fact Extraction & Contradiction Resolution Engine  
> **Repository:** [surendra2304/IntelX](https://github.com/surendra2304/IntelX) (Branch: main)
> **Workspace Path:** d:\FRIDAY Universe\IntelX  

---

## ☁️ 1. Configured service (runtime unverified)

| Attribute | Repository configuration |
| :--- | :--- |
| **Configured Service URL (deployment unverified)** | [https://intelx-mygl.onrender.com](https://intelx-mygl.onrender.com) |
| **Health Check Endpoint** | https://intelx-mygl.onrender.com/health |
| **API key variable (keep value in secret environment)** | `INTELX_API_KEY` (configure a unique secret outside source control) |
| **Authentication Header** | Authorization: Bearer `<configured INTELX_API_KEY>` |
| **Configured database topology (runtime unverified)** | Turso LibSQL Cloud DB (Turso connector configured (active DB path and capacity unverified)) |
| **Configured database URL or namespace (not a secret)** | https://intelx-db-surendra2304.aws-ap-south-1.turso.io |
| **Configured host (plan, region, and runtime unverified)** | Render service configured (current plan, region, and deployment unverified) |

---

## 🎯 2. Purpose & Responsibilities

### What IntelX IS:
* IntelX is an evidence-driven research and fact-extraction monolith. It ingests multi-source web documents, extracts verbatim proposition spans, tracks mathematical confidence ledgers, resolves contradictions, and publishes verified executive reports.

### What IntelX DOES:
* Operates as the **Multi-Source Evidence Research, Fact Extraction & Contradiction Resolution Engine** within the 9-agent FRIDAY Universe.
* Communicates directly with peer agents via authenticated REST and WebSocket protocols.
* Persists private long-term memory records to **Memora** under memora://intelx/private.

---

## 🌐 3. Ecosystem endpoint configuration

These variable names and URLs are references only; they do not prove live communication. Set real credentials in secret environments.

```env
# ============================================================================== #
#               FRIDAY UNIVERSE MASTER ECOSYSTEM CONFIGURATION                  #
# ============================================================================== #

# 1. ⚡ Inference AI Multi-Model Gateway (configured provider pool)
INFERENCE_URL=https://inference-h7bn.onrender.com
INFERENCE_API_KEY=<configure locally; do not commit>

# 2. Memora cloud memory service (active backend/capacity not verified)
MEMORA_URL=https://memora-cavc.onrender.com
MEMORA_API_KEY=<configure locally; do not commit>

# 3. 📈 Stratex Paper/Testnet Strategy Platform (Binance Futures)
STRATEX_URL=https://stratex-8wj1.onrender.com
STRATEX_API_KEY=<configure locally; do not commit>

# 4. IntelX research service (active storage backend not verified)
INTELX_URL=https://intelx-mygl.onrender.com
INTELX_API_KEY=<configure locally; do not commit>

# 5. 🔮 Futuris Calibrated Predictive Forecasting Engine
FUTURIS_URL=https://futuris-th6f.onrender.com
FUTURIS_API_KEY=<configure locally; do not commit>

# 6. 🌐 Cortex Autonomous Web Operations & Intelligence
CORTEX_URL=https://cortex-0m7c.onrender.com
CORTEX_API_KEY=<configure locally; do not commit>

# 7. 🛠️ Forge Local Software Engineering Engine
FORGE_URL=https://forge-e9kl.onrender.com
FORGE_API_KEY=<configure locally; do not commit>

# 8. 🛡️ Sentinel Local Cybersecurity & Threat Defense Shield
SENTINEL_URL=https://sentinel-a861.onrender.com
SENTINEL_API_KEY=<configure locally; do not commit>

# 9. 🤖 FRIDAY Central Desktop Operating System
FRIDAY_URL=https://friday-zw59.onrender.com
FRIDAY_API_KEY=<configure locally; do not commit>
```

---

## 🤖 4. Repository guide

When opening this repository:
* **Identity:** You are working inside **IntelX** (d:\FRIDAY Universe\IntelX).
* **Configured URL (deployment unverified): https://intelx-mygl.onrender.com.
* **Authentication:** Incoming requests require the configured `INTELX_API_KEY`; set separate, strong secrets for each service.
* **Never Fake Tests:** All tests and verifications must be executed against real code and real endpoints.
* **No Unapproved Git Pushes:** Keep modifications local unless explicitly instructed to push.
