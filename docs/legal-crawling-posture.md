# INTELX Legal, Crawling & Ingestion Posture

This document sets forth the legal, ethical, and operational standards governing web ingestion, document retrieval, and robot etiquette in **INTELX**.

---

## 1. Ethical Ingestion & Robot Etiquette

1. **User-Agent Identification**:
   All HTTP discovery and content retrieval requests made by `HttpFetchConnector` identify themselves with a standard user-agent header containing operator contact information:
   ```
   User-Agent: IntelX-Research-Bot/0.1 (+https://github.com/surendra2304/IntelX; contact@intelx-research.local)
   ```

2. **Robots.txt & Meta Rules**:
   - `HttpFetchConnector` inspects `robots.txt` before fetching external pages.
   - Respects `Disallow` directives and `X-Robots-Tag: noindex, noarchive`.

3. **Per-Domain Rate Limiting**:
   - Outbound HTTP requests to external domains are automatically rate-limited (minimum 500ms delay between consecutive requests to the same domain) to prevent server load or accidental denial-of-service.

4. **No Paywall or Authentication Bypass**:
   - INTELX never attempts to circumvent paywalls, access control headers, or authentication challenges (`401 Unauthorized` and `403 Forbidden` responses immediately terminate the retrieval branch).

---

## 2. Ingestion Defense & Content Quarantine

- **No Ingestion Code Execution**: Ingested files (PDFs, DOCX, CSVs, HTML) are converted strictly to plain text with all scripts, macros, and embedded binaries stripped.
- **SSRF Network Boundaries**: Outbound fetches to `localhost`, RFC 1918 private subnets (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), and AWS/GCP cloud metadata endpoints (`169.254.169.254`) are intercepted and rejected at the socket layer.

---

## 3. Data Retention & Takedown Procedures

- **Retention Limits**: Raw fetched documents are purged automatically after 30 days (`INTELX_RAW_RETENTION_DAYS`).
- **Takedown & Retraction Requests**: Operators can retract claims, delete specific sources, or blacklist entire domains via `/api/v1/sources/{id}/trust` or `/api/v1/claims/{id}/retract`.
- **Takedown Contact**: Notice of takedown or removal requests should be addressed to the configured administrative contact (`legal-takedowns@intelx-research.local`).

---

## 4. Research & Personal Use Notice

> **Notice**: INTELX is engineered for transformative, non-consumptive computational research, automated fact-checking, and evidence synthesis. Users are responsible for ensuring their usage complies with relevant copyright laws, terms of service, and organizational policies in their respective jurisdictions.
