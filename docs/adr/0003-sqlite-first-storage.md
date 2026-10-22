# ADR 0003: SQLite-First Storage Architecture with WAL Mode

## Status
Accepted

## Context
INTELX is designed to operate seamlessly out-of-the-box on developer laptops, edge workstations, air-gapped lab environments, and standard cloud containers without requiring a fleet of external database services.

## Decision
We adopted SQLite as the default primary database engine using `aiosqlite` and SQLAlchemy 2.0 with:
- `PRAGMA journal_mode = WAL;`
- `PRAGMA synchronous = NORMAL;`
- `PRAGMA busy_timeout = 60000;`
- `PRAGMA foreign_keys = ON;`
- Native SQLite FTS5 virtual tables with insert/delete sync triggers.

The database URL can be swapped to PostgreSQL (`postgresql+asyncpg://...`) for multi-replica horizontal scaling via `INTELX_DB_URL`.

## Consequences
### Positive
- **Zero-Config Setup**: `make dev` works immediately without spinning up a Docker daemon or DB container.
- **Embedded FTS5**: Full-text claim and chunk search without Lucene/Elasticsearch overhead.
- **File Portability**: Research databases can be snapshotted (`VACUUM INTO`) and shared as self-contained `.db` files.

### Negative
- Parallel write concurrency in SQLite requires busy timeout locks; high write-throughput enterprise deployments should migrate to PostgreSQL.
