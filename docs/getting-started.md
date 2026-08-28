# Getting Started with INTELX

Welcome to **INTELX** — the evidence-driven intelligence research monolith.

---

## ⚡ 3-Command Quickstart (Zero API Keys Needed)

INTELX comes pre-configured with **Mock Mode**, allowing you to initialize the database, seed a demo job, and run the server locally without any external LLM or search API keys:

```bash
# 1. Install dependencies & initialize database schema
make setup && make migrate

# 2. Seed realistic evaluation fixtures and queue a demo research run
make seed-demo

# 3. Launch server and interactive web workspace
make dev
```

Now open **[http://localhost:8000](http://localhost:8000)** in your browser:
- Log in with the default seeded Admin key: `dev-admin-key`
- View the pre-seeded demo job running through the discovery and synthesis pipeline.
- Click any finding to inspect its citation provenance in the slide-out drawer.

---

## 🧪 Running Automated Tests & Quality Gates

```bash
# Run the 84-test unit and integration test suite
make test

# Run the 8-task golden evaluation benchmark harness
make eval

# Verify code formatting and linting rules
make lint
```

---

## 🛠️ CLI Operations

You can also interact with INTELX via the `intelx` command line interface:

```bash
intelx serve               # Start FastAPI server on port 8000
intelx worker              # Start background task execution worker
intelx migrate             # Apply database migrations
intelx seed-demo           # Seed local fixture data and create demo run
intelx eval                # Run deterministic evaluation harness
intelx purge --days 30     # Run retention purge for old raw cache files
intelx verify-audit        # Verify cryptographic audit chain integrity
```
