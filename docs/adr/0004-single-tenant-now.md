# ADR 0004: Single-Tenant Workspaces (and Multi-Tenant Evolution Path)

## Status
Accepted

## Context
Initial target users are intelligence analysts, R&D labs, and individual researchers who require complete data sovereignty, zero telemetry leakage, and strict local boundary controls.

## Decision
INTELX v0.1.0 is engineered as a single-organization / single-tenant platform governed by role-based API keys (`ADMIN`, `MEMBER`). All data in a given SQLite instance belongs to the host organization.

### Multi-Tenant Migration Path
To evolve INTELX into a multi-tenant cloud SaaS:
1. Introduce `tenant_id: str` column indexed on `research_runs`, `sources`, `claims`, `entities`, and `audit_events`.
2. Add PostgreSQL Row-Level Security (RLS) policies enforcing `tenant_id = current_setting('app.current_tenant')`.
3. Namespace object storage keys in S3/MinIO under `/<tenant_id>/raw/` and `/<tenant_id>/artifacts/`.

## Consequences
### Positive
- Maximizes security and simplicity for single-team deployments.
- Avoids tenant-leakage security bugs during MVP development.

### Negative
- Running separate departments currently requires separate INTELX container instances and SQLite databases.
