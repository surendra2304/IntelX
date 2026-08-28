# ADR 0001: Relational Schema for Evidence Provenance (Over Graph DB)

## Status
Accepted

## Context
INTELX models complex evidence graphs: Finding $\to$ Claim $\to$ Evidence $\to$ Document $\to$ Source, alongside entity triplets (`source_entity`, `predicate`, `target_entity`). We considered adopting a specialized graph database (e.g., Neo4j) versus a standard relational model with SQL indexing.

## Decision
We implemented a strict relational schema with 18 typed SQLAlchemy models backed by SQLite (WAL mode) and PostgreSQL. Graph queries (such as entity relationship derivation and claim clustering) are executed via relational joins and indexed foreign keys.

## Consequences
### Positive
- **Zero External Operational Burden**: Users can run INTELX as a standalone zero-dependency binary/container without maintaining a separate graph server cluster.
- **ACID Transactions & Foreign Key Enforcement**: Exact verbatim span integrity and cryptographic audit chain hashing can be enforced atomically in a single relational commit.
- **Full Text Search (FTS5)**: Native integration with SQLite FTS5 full-text indexing without requiring an external Elasticsearch or Lucene service.

### Negative
- Multi-hop graph traversals with arbitrary depth require recursive CTEs or application-level traversals.
