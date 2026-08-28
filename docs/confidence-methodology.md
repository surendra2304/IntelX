# INTELX Composite Confidence Scoring Methodology (v1.0)

This document specifies the deterministic mathematical formula, penalty weights, and verification rules used to compute confidence scores for all claims in **INTELX**.

---

## 1. Core Philosophy

> **Confidence is computed from verifiable evidence attributes, NEVER generated as arbitrary LLM self-assessment.**

INTELX uses a deterministic composite formula implemented in [`intelx/core/confidence.py`](file:///d:/IntelX/intelx/core/confidence.py) that evaluates:
1. Primary source authority (trust tier).
2. Independent corroboration count (evaluated via 3-gram Jaccard overlap).
3. Active contradictions and dispute status.
4. Prompt injection and security quarantine penalties.

---

## 2. Mathematical Formulation (v1.0)

The composite confidence $C$ for an individual claim is computed as:

$$C = \min\left(1.0, \, \max\left(0.05, \, B + \Delta_{\text{corroboration}} - \sum P_{\text{penalties}}\right)\right)$$

### 1. Base Score ($B$)
The initial score based on the originating source's `TrustTier`:
- `TRUSTED`: $B = 0.75$
- `STANDARD`: $B = 0.60$
- `QUARANTINE`: $B = 0.35$ (and maximum confidence is hard-capped at $0.45$)

### 2. Independent Corroboration Boost ($\Delta_{\text{corroboration}}$)
For each independent corroboration $i$ (where domain, publisher, and 3-gram quote Jaccard $< 0.5$):
- Boost: $+0.12$ per independent source (up to a maximum boost of $+0.24$ for $\ge 2$ corroborations).

### 3. Penalty Deductions ($\sum P$)
- **Contradiction / Dispute Penalty**: $-0.40$ if the claim is contested by opposing evidence.
- **Prompt Injection Risk Penalty**: $-0.25$ if the originating source was flagged for prompt injection attempts.
- **Stale Temporal Data Penalty**: $-0.10$ if superseded by recent benchmark evidence.

---

## 3. Semantic Confidence Labels

Every numeric score maps deterministically to a human-readable confidence label:

| Numeric Range | Semantic Label | Meaning & Usage |
|---|---|---|
| $C \ge 0.80$ | **HIGH** | Multiple independent corroborations from standard/trusted sources with zero active contradictions. |
| $0.50 \le C < 0.80$ | **MODERATE** | Backed by a standard source with single corroboration or minor unverified aspects. |
| $C < 0.50$ | **LOW** | Uncorroborated, quarantined, or contested claims. Material statements must highlight epistemic gaps. |

---

## 4. Worked Example Calculations

### Scenario A: High-Confidence Benchmark
- **Source**: `nature-energy.org` (`TrustTier.STANDARD`, $B = 0.60$)
- **Corroborations**: 2 independent lab replications ($\Delta = +0.24$)
- **Penalties**: None ($P = 0.0$)
- **Calculation**:
  $$C = 0.60 + 0.24 - 0.0 = \mathbf{0.84} \implies \text{HIGH CONFIDENCE}$$

### Scenario B: Contradictory Measurement
- **Source**: `nature.com` (`TrustTier.STANDARD`, $B = 0.60$)
- **Corroborations**: 1 corroboration ($\Delta = +0.12$)
- **Penalties**: Opposing PRL paper proves SEI degradation ($P = -0.40$)
- **Calculation**:
  $$C = 0.60 + 0.12 - 0.40 = \mathbf{0.32} \implies \text{LOW CONFIDENCE (DISPUTED)}$$

### Scenario C: Quarantined Wire Ingestion
- **Source**: `unknown-blog.io` (`TrustTier.QUARANTINE`, $B = 0.35$)
- **Corroborations**: None ($\Delta = 0.0$)
- **Penalties**: None ($P = 0.0$)
- **Calculation**:
  $$C = \min(0.45, \, 0.35) = \mathbf{0.35} \implies \text{LOW CONFIDENCE (UNCORROBORATED)}$$
