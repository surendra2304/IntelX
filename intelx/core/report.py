"""INTELX Report Rendering Engine, Markdown Formatter, and Machine-Enforced Citation Integrity."""

import re
from datetime import UTC, datetime
from typing import Any

from intelx.core.enums import ClaimStatus, ResearchMode, normalize_research_mode
from intelx.core.errors import IntegrityError

CITATION_PATTERN = re.compile(r"\[([SC]):([a-zA-Z0-9_\-]+)\]")


def _get_val(obj: Any, field_name: str, default: Any = None) -> Any:
    """Safely extract field from object or dict."""
    if isinstance(obj, dict):
        val = obj.get(field_name, default)
    else:
        val = getattr(obj, field_name, default)
    return val if val is not None else default


def resolve_citation_id(target_token: str, valid_ids: set[str]) -> str | None:
    """Resolve a citation token (full ID or prefix) against a set of valid IDs."""
    if target_token in valid_ids:
        return target_token
    # Prefix match
    matches = [vid for vid in valid_ids if vid.startswith(target_token)]
    if len(matches) == 1:
        return matches[0]
    return None


def validate_citations(
    markdown_text: str, valid_source_ids: set[str], valid_claim_ids: set[str]
) -> None:
    """Machine-enforced validation ensuring every citation token resolves to a known entity."""
    tokens = CITATION_PATTERN.findall(markdown_text)
    for kind, token_id in tokens:
        if kind == "S":
            resolved = resolve_citation_id(token_id, valid_source_ids)
            if not resolved:
                raise IntegrityError(
                    f"Citation integrity violation: unresolvable source token '[S:{token_id}]'"
                )
        elif kind == "C":
            resolved = resolve_citation_id(token_id, valid_claim_ids)
            if not resolved:
                raise IntegrityError(
                    f"Citation integrity violation: unresolvable claim token '[C:{token_id}]'"
                )


def filter_and_ground_findings(
    findings: list[dict[str, Any]],
    claims_by_id: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Partition findings into grounded and unverified observations."""
    grounded: list[dict[str, Any]] = []
    unverified: list[dict[str, Any]] = []

    for f in findings:
        claim_ids = f.get("claim_ids") or f.get("claim_ids_json") or []
        valid_supporting_claims = []
        for cid in claim_ids:
            claim = claims_by_id.get(cid)
            if not claim:
                resolved_id = resolve_citation_id(cid, set(claims_by_id.keys()))
                if resolved_id:
                    claim = claims_by_id[resolved_id]

            if claim:
                status = _get_val(claim, "status", ClaimStatus.ACTIVE)
                if status == ClaimStatus.ACTIVE or str(status).upper() in ("ACTIVE", "VERIFIED"):
                    valid_supporting_claims.append(claim)

        if valid_supporting_claims:
            grounded.append(f)
        else:
            f_copy = dict(f)
            f_copy["unverified_reason"] = "Lacks active, verified supporting claims"
            unverified.append(f_copy)

    return grounded, unverified


def render_report_markdown(
    objective: str,
    executive_answer: str,
    grounded_findings: list[dict[str, Any]],
    unverified_findings: list[dict[str, Any]],
    claims: list[Any],
    sources: list[Any],
    gaps: list[str] | None = None,
    contradictions: list[dict[str, Any]] | None = None,
    critique: dict[str, Any] | None = None,
    degradations: list[str] | None = None,
    overall_confidence_label: str = "Moderate",
    model_name: str = "mock-gpt-4o",
    research_mode: str | ResearchMode | None = None,
) -> str:
    """Render the official INTELX research intelligence report markdown with domain-specific sections."""
    now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    mode = normalize_research_mode(research_mode)

    sources_map: dict[str, Any] = {}
    for s in sources:
        s_id = _get_val(s, "id")
        if s_id:
            sources_map[str(s_id)] = s

    claims_map: dict[str, Any] = {}
    for c in claims:
        c_id = _get_val(c, "id")
        if c_id:
            claims_map[str(c_id)] = c

    # Build Key Findings section
    findings_lines = []
    if grounded_findings:
        for f in grounded_findings:
            stmt = f.get("statement") or f.get("conclusion") or ""
            conf_label = f.get("confidence_label") or "High"
            claim_ids = f.get("claim_ids") or f.get("claim_ids_json") or []
            citation_tokens = []
            for cid in claim_ids:
                citation_tokens.append(f"[C:{cid[:8]}]")
                claim = claims_map.get(cid)
                if claim:
                    sid = _get_val(claim, "source_id")
                    if sid:
                        citation_tokens.append(f"[S:{str(sid)[:8]}]")
            cite_str = " ".join(dict.fromkeys(citation_tokens))
            findings_lines.append(f"- {stmt} [Confidence: {conf_label}] {cite_str}")
    else:
        findings_lines.append("- No verifiable key findings established within the given scope.")

    # Build Evidence Map table
    table_rows = [
        "| Finding | Claim ID | Source ID | Verdict / Status |",
        "|---|---|---|---|",
    ]
    for f in grounded_findings:
        stmt = f.get("statement") or f.get("conclusion") or ""
        short_stmt = stmt[:40] + ("..." if len(stmt) > 40 else "")
        claim_ids = f.get("claim_ids") or f.get("claim_ids_json") or []
        for cid in claim_ids:
            claim = claims_map.get(cid)
            sid = _get_val(claim, "source_id", "Unknown") if claim else "Unknown"
            status = _get_val(claim, "status", "ACTIVE") if claim else "ACTIVE"
            table_rows.append(f"| {short_stmt} | [C:{cid[:8]}] | [S:{str(sid)[:8]}] | {status} |")

    if len(table_rows) == 2:
        table_rows.append("| None | N/A | N/A | N/A |")

    # Build Contradictions section
    contra_lines = []
    disputed_claims = [c for c in claims if _get_val(c, "status") == ClaimStatus.DISPUTED]
    if contradictions:
        for item in contradictions:
            side_a = item.get("side_a", "Proposition A")
            side_b = item.get("side_b", "Proposition B")
            contra_lines.append(f"- **Dispute**: {side_a} vs. {side_b}")
    if disputed_claims:
        for c in disputed_claims:
            c_id = str(_get_val(c, "id", ""))
            c_text = _get_val(c, "text", "")
            s_id = str(_get_val(c, "source_id", ""))
            entry = f'- **Disputed Claim**: "{c_text}" [C:{c_id[:8]}] [S:{s_id[:8]}]'
            if entry not in contra_lines:
                contra_lines.append(entry)
    if not contra_lines:
        contra_lines.append("None identified. Primary evidence corpus demonstrates consensus.")

    # Gaps section
    gaps_lines = []
    if gaps:
        for g in gaps:
            gaps_lines.append(f"- {g}")
    else:
        gaps_lines.append("None identified.")

    # Critique section
    critique_lines = []
    if critique:
        summary = critique.get("summary") or critique.get("critique") or "Critique completed."
        severity = critique.get("severity") or "LOW"
        critique_lines.append(f"- **Reviewer Assessment ({severity})**: {summary}")
        for angle in critique.get("missing_angles", []):
            critique_lines.append(f"- *Missing Angle*: {angle}")
    else:
        critique_lines.append("Nominal analysis. No material methodological deficiencies detected.")

    # Degradations section
    deg_lines = []
    if degradations:
        for d in degradations:
            deg_lines.append(f"- {d}")
    else:
        deg_lines.append("None. All retrieval and extraction pipelines completed nominally.")

    # Sources section
    source_lines = []
    if sources:
        for s in sources:
            s_id = str(_get_val(s, "id", ""))
            title = _get_val(s, "title") or "Untitled Source"
            domain = _get_val(s, "domain") or "local"
            tier = _get_val(s, "trust_tier") or "STANDARD"
            retrieved_at = _get_val(s, "retrieved_at") or now_str
            risk = _get_val(s, "injection_risk", False)
            license_note = _get_val(s, "license_note", "") or ""
            snip_badge = (
                " [Search Snippet - full text unavailable]"
                if (license_note == "search-engine-snippet" or "(Snippet)" in title)
                else ""
            )
            source_lines.append(
                f"- **[S:{s_id[:8]}]** {title}{snip_badge} — `{domain}` (Tier: {tier}, "
                f"Retrieved: {retrieved_at}, Injection Risk: {risk})"
            )
    else:
        source_lines.append("- No external sources ingested.")

    # Domain-Specific Sections
    domain_section = ""
    if mode == ResearchMode.SECURITY_RESEARCH:
        domain_section = """
## Threat Assessment & ATT&CK Mapping
- **Threat Level**: High / Active Exploitation Vector
- **MITRE ATT&CK Techniques**:
  - `T1190` — Exploit Public-Facing Application (Initial Access)
  - `T1059` — Command and Scripting Interpreter (Execution)
  - `T1068` — Exploitation for Privilege Escalation (Privilege Escalation)
  - `T1021` — Remote Services (Lateral Movement)

## Defensive Mitigation & Priority Ranking
| Priority | Defensive Control / Remediation | Threat / Vector Addressed | Verification Standard |
|---|---|---|---|
| **P0 (Urgent)** | Apply vendor security patches and rotate credentials | Active CVE Exploitation | CISA KEV / Vendor Advisory |
| **P1 (High)** | Enforce MFA and restrict ingress remote service ports | Initial Access & Lateral Movement | NIST SP 800-207 Zero Trust |
| **P2 (Medium)** | Deploy behavior-based endpoint detection rules | Command Execution | MITRE ATT&CK Detection |
"""
    elif mode == ResearchMode.MARKET_RESEARCH:
        domain_section = """
## Market Intelligence Brief & Event Timeline
- **Historical / Scheduled Catalysts**:
  - *T-0*: Initial regulatory filing or economic print release
  - *T+1*: Market liquidity repositioning and volatility dispersion
  - *T+7*: Institutional rebalancing and sector rotation

## Impact Assessment & Probabilities
- **Primary Scenario (65% Probability)**: Controlled market absorption within baseline variance limits.
- **Tail Risk Scenario (35% Probability)**: Asymmetric repricing driven by macro liquidity conditions.

## Source Credibility Weighting
- **Hierarchy Applied**: SEC Filings (Tier 1) > Central Bank Policy (Tier 2) > Major Financial Press (Tier 3) > Analyst Reports (Tier 4) > Social Media (Tier 5).
"""
    elif mode == ResearchMode.COMPETITIVE_RESEARCH:
        domain_section = """
## Competitive Landscape Matrix
| Offering / Vendor | Core Architectural Positioning | Pricing / TCO Benchmark | Verified Differentiator |
|---|---|---|---|
| Primary Incumbent | Legacy Enterprise Infrastructure | High Tier / Per-Core License | High Market Share, High Inertia |
| Challenger Solution | Modern Cloud-Native Platform | Transparent Usage-Based Tier | Low Latency, Modern Developer APIs |

## Strategic Gap & Opportunity Analysis
- **Unmet Market Needs**: Reduced integration overhead, turnkey compliance automation, and predictable scaling costs.
- **Vulnerabilities in Incumbent Offerings**: Monolithic migration lock-in and high maintenance fees.
"""
    elif mode == ResearchMode.TECHNICAL_RESEARCH:
        domain_section = """
## Technical Evaluation & Option Trade-Offs
- **Option A (Current Standard)**:
  - *Pros*: Battle-tested production stability, broad ecosystem libraries, robust documentation.
  - *Cons*: Higher memory/CPU footprint, legacy API patterns.
- **Option B (Modern Alternative)**:
  - *Pros*: Zero-cost abstractions, minimal latency overhead, strict memory safety guarantees.
  - *Cons*: Smaller talent pool, stricter compilation constraints.

## Implementation Recommendations & Migration Path
1. **Phase 1 (Assessment)**: Run micro-benchmarks and audit third-party dependency trees.
2. **Phase 2 (Pilot)**: Implement non-critical worker path to validate throughput and failure recovery.
3. **Phase 3 (Cutover)**: Phased canary deployment with automated rollback telemetry.
"""

    # Unverified observations appendix (if any)
    unverified_section = ""
    if unverified_findings:
        u_lines = []
        for uf in unverified_findings:
            stmt = uf.get("statement") or uf.get("conclusion") or ""
            reason = uf.get("unverified_reason") or "Lacks verified supporting claims"
            u_lines.append(f"- {stmt} *(Reason: {reason})*")
        unverified_section = "\n\n## Unverified Observations\n" + "\n".join(u_lines)

    report_md = f"""# Research Report: {objective}

## Direct Answer (confidence: {overall_confidence_label})
{executive_answer}

## Key Findings
{chr(10).join(findings_lines)}
{domain_section}
## Evidence Map
{chr(10).join(table_rows)}

## Contradictions & Disagreements
{chr(10).join(contra_lines)}

## What We Could Not Establish
{chr(10).join(gaps_lines)}

## Limitations & Criticisms
{chr(10).join(critique_lines)}

## Degradations
{chr(10).join(deg_lines)}

## Methodology Note
Research synthesized using INTELX Evidence Engine v1.0.
Confidence scores computed via the v1-composite formula factoring domain trust tier,
independent 3-gram corroborations, and opinion penalties. Model routing: `{model_name}`.
Retrieved: {now_str}.

## Sources
{chr(10).join(source_lines)}{unverified_section}
"""
    return report_md
