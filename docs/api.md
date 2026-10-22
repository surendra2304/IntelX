# INTELX REST API v1 Reference & Curl Guide

This document provides a comprehensive reference for all versioned HTTP endpoints under `/api/v1` with authentication and request examples.

---

## 1. Authentication & Headers

All API requests require a Bearer token in the `Authorization` header:

```bash
Authorization: Bearer <API_KEY>
```

Optional headers:
- `Idempotency-Key: <unique-uuid>`: Ensures identical POST requests within 24 hours return the cached response without re-executing.

---

## 2. Research Investigation Lifecycle

### 1. Submit Research Job
```bash
curl -X POST "http://localhost:8000/api/v1/research/jobs" \
     -H "Authorization: Bearer dev-admin-key" \
     -H "Content-Type: application/json" \
     -d '{
       "objective": "Assess sodium-ion battery cathode formulations and recent commercial cycling benchmarks",
       "scope": {
         "depth": "standard",
         "max_sources": 25,
         "allowed_domains": ["nature-energy.org", "arxiv.org"],
         "budget": {
           "max_usd": 5.00,
           "max_minutes": 15
         }
       }
     }'
```

### 2. Poll Job Telemetry & State
```bash
curl -X GET "http://localhost:8000/api/v1/research/jobs/3d84ed18-e688-4042-af27-4742354716cd" \
     -H "Authorization: Bearer dev-admin-key"
```

### 3. Stream Real-Time Events (Server-Sent Events)
```bash
curl -N -X GET "http://localhost:8000/api/v1/research/jobs/3d84ed18-e688-4042-af27-4742354716cd/events/stream" \
     -H "Authorization: Bearer dev-admin-key" \
     -H "Accept: text/event-stream"
```

### 4. Fetch Research Report & Claims
```bash
curl -X GET "http://localhost:8000/api/v1/research/jobs/3d84ed18-e688-4042-af27-4742354716cd/report" \
     -H "Authorization: Bearer dev-admin-key"
```

### 5. Download Artifacts (`report.md`, `report.json`, `evidence_pack.json`, `sources.csv`)
```bash
curl -X GET "http://localhost:8000/api/v1/artifacts/<ARTIFACT_ID>?format=md" \
     -H "Authorization: Bearer dev-admin-key" \
     --output report.md
```

---

## 3. Knowledge Base & Citation Resolvers

### Search Claims & Primary Evidence
```bash
curl -X POST "http://localhost:8000/api/v1/knowledge/query" \
     -H "Authorization: Bearer dev-admin-key" \
     -H "Content-Type: application/json" \
     -d '{
       "query": "160 Wh/kg thermal stability",
       "limit": 10
     }'
```

### Inspect Single Citation Payload
```bash
curl -X GET "http://localhost:8000/api/v1/knowledge/citation/C/10f9c2fb" \
     -H "Authorization: Bearer dev-admin-key"
```

---

## 4. Governance, Review, and Audit Trails

### Submit Review Decision on Paused Jobs (Admin)
```bash
curl -X POST "http://localhost:8000/api/v1/review/3d84ed18-e688-4042-af27-4742354716cd/decision" \
     -H "Authorization: Bearer dev-admin-key" \
     -H "Content-Type: application/json" \
     -d '{
       "decision": "APPROVED",
       "notes": "Evidence verified by chief researcher."
     }'
```

### Promote or Block Source Trust Tier (Admin)
```bash
curl -X PUT "http://localhost:8000/api/v1/sources/<SOURCE_ID>/trust" \
     -H "Authorization: Bearer dev-admin-key" \
     -H "Content-Type: application/json" \
     -d '{
       "tier": "TRUSTED"
     }'
```

### Retract Erroneous Claim (Admin)
```bash
curl -X POST "http://localhost:8000/api/v1/claims/<CLAIM_ID>/retract" \
     -H "Authorization: Bearer dev-admin-key" \
     -H "Content-Type: application/json" \
     -d '{
       "reason": "Author retracted paper due to electrolyte calibration error."
     }'
```

### Cryptographically Verify Audit Chain Integrity (Admin)
```bash
curl -X GET "http://localhost:8000/api/v1/audit/verify" \
     -H "Authorization: Bearer dev-admin-key"
```

### Trigger Raw Data Retention Purge (Admin)
```bash
curl -X POST "http://localhost:8000/api/v1/admin/retention/purge?days=30" \
     -H "Authorization: Bearer dev-admin-key"
```

---

## 5. FRIDAY Autonomous Delegation & Consumer Endpoints

All FRIDAY endpoints authenticate via `INTELX_FRIDAY_API_KEY` (supplied via `X-API-Key` or `Authorization: Bearer <key>` header) with a sliding window rate limit of **50 req/hour**. Research runs submitted with `priority: "urgent"` automatically skip ahead of queued jobs.

### 1. Delegate Research Job
```bash
curl -X POST "http://localhost:8000/api/v1/friday/research" \
     -H "X-API-Key: <INTELX_FRIDAY_API_KEY>" \
     -H "Content-Type: application/json" \
     -d '{
       "friday_request_id": "friday-req-94a2b1",
       "question": "Assess sodium-ion cathode energy density limits and thermal stability",
       "context": {
         "requesting_system": "sentinel",
         "priority": "urgent",
         "related_incident_id": "inc-sec-2026-08",
         "domain_hint": "security"
       },
       "depth": "standard",
       "budget": {
         "max_sources": 10,
         "max_time_minutes": 15
       },
       "webhook_url": "https://friday.internal/webhook/intelx"
     }'
```

**Response (201 Created)**:
```json
{
  "intelx_run_id": "f53d3000e1844bf2afe6a9da51d40b0e",
  "friday_request_id": "friday-req-94a2b1",
  "status": "QUEUED",
  "estimated_completion": "2026-08-28T23:45:00Z",
  "subquestion_count": 4
}
```

### 2. Poll Run Status, Phase & Progress
```bash
curl -X GET "http://localhost:8000/api/v1/friday/research/f53d3000e1844bf2afe6a9da51d40b0e" \
     -H "X-API-Key: <INTELX_FRIDAY_API_KEY>"
```

### 3. Fetch Structured Findings with Grounded Citations
```bash
curl -X GET "http://localhost:8000/api/v1/friday/research/f53d3000e1844bf2afe6a9da51d40b0e/findings" \
     -H "X-API-Key: <INTELX_FRIDAY_API_KEY>"
```

### 4. Fetch Full Intelligence Report (Markdown + JSON)
```bash
curl -X GET "http://localhost:8000/api/v1/friday/research/f53d3000e1844bf2afe6a9da51d40b0e/report" \
     -H "X-API-Key: <INTELX_FRIDAY_API_KEY>"
```

### 5. Stream Real-Time Events (Server-Sent Events)
```bash
curl -N -X GET "http://localhost:8000/api/v1/friday/research/f53d3000e1844bf2afe6a9da51d40b0e/events" \
     -H "X-API-Key: <INTELX_FRIDAY_API_KEY>" \
     -H "Accept: text/event-stream"
```

### 6. Inspect Disputed Claims & Opposing Evidence
```bash
curl -X GET "http://localhost:8000/api/v1/friday/research/f53d3000e1844bf2afe6a9da51d40b0e/contradictions" \
     -H "X-API-Key: <INTELX_FRIDAY_API_KEY>"
```
