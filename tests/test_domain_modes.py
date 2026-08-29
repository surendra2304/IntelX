"""Tests for Specialized Domain Research Modes, Templates, Credibility Scoring, and Enhancement."""

import pytest

from intelx.agents.planner import PlannerAgent, ResearchQuestionEnhancer
from intelx.core.confidence import compute_confidence_score
from intelx.core.credibility import SourceCredibilityScorer
from intelx.core.enums import ResearchMode, normalize_research_mode
from intelx.core.report import render_report_markdown


def test_research_mode_normalization():
    """Verify normalize_research_mode correctly maps domain hints and subsystem tags."""
    assert normalize_research_mode("security") == ResearchMode.SECURITY_RESEARCH
    assert normalize_research_mode("sentinel") == ResearchMode.SECURITY_RESEARCH
    assert normalize_research_mode("market") == ResearchMode.MARKET_RESEARCH
    assert normalize_research_mode("trading_bot") == ResearchMode.MARKET_RESEARCH
    assert normalize_research_mode("competitive") == ResearchMode.COMPETITIVE_RESEARCH
    assert normalize_research_mode("nexus") == ResearchMode.COMPETITIVE_RESEARCH
    assert normalize_research_mode("technical") == ResearchMode.TECHNICAL_RESEARCH
    assert normalize_research_mode("forge") == ResearchMode.TECHNICAL_RESEARCH
    assert normalize_research_mode("unknown_hint") == ResearchMode.GENERAL
    assert normalize_research_mode(None) == ResearchMode.GENERAL


def test_source_credibility_scorer_security_hierarchy():
    """Verify security domain credibility scoring hierarchy."""
    # Tier 1: MITRE
    s1, l1 = SourceCredibilityScorer.score_source(
        "https://attack.mitre.org/techniques/T1190", "security"
    )
    assert s1 == 1.00
    assert "MITRE" in l1

    # Tier 2: CISA / NIST
    s2, l2 = SourceCredibilityScorer.score_source(
        "https://cisa.gov/news-events/cybersecurity-advisories", "security"
    )
    assert s2 == 0.90
    assert "CISA" in l2

    # Tier 3: Vendor Advisory
    s3, l3 = SourceCredibilityScorer.score_source(
        "https://msrc.microsoft.com/update-guide", "security"
    )
    assert s3 == 0.80
    assert "Vendor" in l3

    # Tier 4: Security Research Blog
    s4, l4 = SourceCredibilityScorer.score_source(
        "https://bleepingcomputer.com/news/security", "security"
    )
    assert s4 == 0.65
    assert "Publication" in l4

    # Tier 5: Community Forum
    s5, l5 = SourceCredibilityScorer.score_source("https://reddit.com/r/netsec", "security")
    assert s5 == 0.30
    assert "Forum" in l5


def test_source_credibility_scorer_market_hierarchy():
    """Verify market domain credibility scoring hierarchy."""
    # Tier 1: SEC Filings
    s1, l1 = SourceCredibilityScorer.score_source(
        "https://www.sec.gov/edgar/searchedgar/companysearch", "market"
    )
    assert s1 == 1.00
    assert "SEC" in l1

    # Tier 2: Central Bank
    s2, l2 = SourceCredibilityScorer.score_source(
        "https://federalreserve.gov/monetarypolicy", "market"
    )
    assert s2 == 0.95
    assert "Central Bank" in l2

    # Tier 3: Major Financial Press
    s3, l3 = SourceCredibilityScorer.score_source("https://bloomberg.com/news/articles", "market")
    assert s3 == 0.80
    assert "Financial Publication" in l3

    # Tier 4: Institutional Equity Research
    s4, l4 = SourceCredibilityScorer.score_source("https://morningstar.com/stocks", "market")
    assert s4 == 0.70
    assert "Institutional" in l4

    # Tier 5: Social / Retail
    s5, l5 = SourceCredibilityScorer.score_source("https://stocktwits.com/symbol/NVDA", "market")
    assert s5 == 0.25
    assert "Social" in l5


def test_source_credibility_scorer_technical_hierarchy():
    """Verify technical domain credibility scoring hierarchy."""
    # Tier 1: Official Docs
    s1, l1 = SourceCredibilityScorer.score_source(
        "https://docs.python.org/3/library/asyncio.html", "technical"
    )
    assert s1 == 1.00
    assert "Official Documentation" in l1

    # Tier 2: Standards / RFCs
    s2, l2 = SourceCredibilityScorer.score_source(
        "https://rfc-editor.org/rfc/rfc7807.txt", "technical"
    )
    assert s2 == 0.95
    assert "Standards Body" in l2

    # Tier 3: Peer-Reviewed
    s3, l3 = SourceCredibilityScorer.score_source("https://arxiv.org/abs/2401.99999", "technical")
    assert s3 == 0.90
    assert "Academic" in l3

    # Tier 4: Technical Conferences
    s4, l4 = SourceCredibilityScorer.score_source(
        "https://usenix.org/conference/osdi24", "technical"
    )
    assert s4 == 0.75
    assert "Conference" in l4

    # Tier 5: Developer Blogs
    s5, l5 = SourceCredibilityScorer.score_source(
        "https://medium.com/@dev/optimizing-fastapi", "technical"
    )
    assert s5 == 0.50
    assert "Developer Blog" in l5


def test_confidence_formula_with_source_credibility():
    """Verify credibility score factors into confidence formula v1."""
    # 1. Neutral credibility (0.70) has zero adjustment
    score_neutral, _, details_neutral = compute_confidence_score(
        strongest_tier="STANDARD",
        independent_corroborations=1,
        credibility_score=0.70,
    )
    assert details_neutral["credibility_bonus"] == 0.0

    # 2. High authority source (1.00) gives positive bonus
    score_high, _, details_high = compute_confidence_score(
        strongest_tier="STANDARD",
        independent_corroborations=1,
        credibility_score=1.00,
    )
    assert details_high["credibility_bonus"] > 0.0
    assert score_high > score_neutral

    # 3. Low authority source (0.25) applies deduction
    score_low, _, details_low = compute_confidence_score(
        strongest_tier="STANDARD",
        independent_corroborations=1,
        credibility_score=0.25,
    )
    assert details_low["credibility_bonus"] < 0.0
    assert score_low < score_neutral


def test_research_question_enhancer_all_modes():
    """Verify ResearchQuestionEnhancer generates domain-specific subquestions."""
    # 1. Security mode
    q_sec = "Evaluate CVE-2026-1049 remote code execution in open-source redis cluster"
    sub_sec = ResearchQuestionEnhancer.enhance_question(q_sec, "security")
    assert len(sub_sec) == 4
    assert any("threat actors" in s.lower() for s in sub_sec)
    assert any("exploitation status" in s.lower() for s in sub_sec)
    assert any("mitre att&ck" in s.lower() for s in sub_sec)
    assert any("defensive mitigation" in s.lower() for s in sub_sec)

    # 2. Market mode
    q_mkt = "Impact of central bank liquidity adjustments on sovereign bond yields"
    sub_mkt = ResearchQuestionEnhancer.enhance_question(q_mkt, "market")
    assert len(sub_mkt) == 4
    assert any("market-moving events" in s.lower() for s in sub_mkt)
    assert any("regulatory filings" in s.lower() or "central bank" in s.lower() for s in sub_mkt)
    assert any("institutional positioning" in s.lower() for s in sub_mkt)

    # 3. Competitive mode
    q_comp = "Analyze enterprise vector database market positioning and pricing models"
    sub_comp = ResearchQuestionEnhancer.enhance_question(q_comp, "competitive")
    assert len(sub_comp) == 4
    assert any("market incumbents" in s.lower() for s in sub_comp)
    assert any("feature-by-feature" in s.lower() for s in sub_comp)
    assert any("pricing tiers" in s.lower() for s in sub_comp)

    # 4. Technical mode
    q_tech = "Assess migration from REST to gRPC for high-throughput microservices"
    sub_tech = ResearchQuestionEnhancer.enhance_question(q_tech, "technical")
    assert len(sub_tech) == 4
    assert any("technical architecture" in s.lower() for s in sub_tech)
    assert any("trade-offs" in s.lower() for s in sub_tech)
    assert any("migration path" in s.lower() for s in sub_tech)


@pytest.mark.asyncio
async def test_planner_agent_with_domain_hint():
    """Verify PlannerAgent utilizes domain templates when domain_hint is present."""
    planner = PlannerAgent()
    scope = {"context": {"domain_hint": "security", "requesting_system": "sentinel"}}
    plan = await planner.execute(
        objective="Assess Apache HTTP Server memory corruption vulnerability CVE-2026-4412",
        scope=scope,
    )
    assert plan is not None
    assert len(plan.subquestions) >= 3
    assert any(
        "threat" in sq.lower()
        or "mitre" in sq.lower()
        or "cve" in sq.lower()
        or "mitigation" in sq.lower()
        for sq in plan.subquestions
    )


def test_domain_specific_report_rendering():
    """Verify render_report_markdown includes domain-specific headings and templates."""
    # 1. Security mode
    md_sec = render_report_markdown(
        objective="Security Assessment",
        executive_answer="Critical RCE vulnerability verified.",
        grounded_findings=[{"statement": "Active exploitation observed.", "claim_ids": ["c1"]}],
        unverified_findings=[],
        claims=[{"id": "c1", "text": "Exploit available", "source_id": "s1", "status": "ACTIVE"}],
        sources=[{"id": "s1", "title": "CVE Advisory", "domain": "cve.org"}],
        research_mode="security",
    )
    assert "## Threat Assessment & ATT&CK Mapping" in md_sec
    assert "## Defensive Mitigation & Priority Ranking" in md_sec
    assert "P0 (Urgent)" in md_sec
    assert "T1190" in md_sec

    # 2. Market mode
    md_mkt = render_report_markdown(
        objective="Market Brief",
        executive_answer="Central bank rate cut impacts equity valuations.",
        grounded_findings=[{"statement": "Bond yields declined.", "claim_ids": ["c1"]}],
        unverified_findings=[],
        claims=[{"id": "c1", "text": "Yields fell 25bps", "source_id": "s1", "status": "ACTIVE"}],
        sources=[{"id": "s1", "title": "Fed Release", "domain": "federalreserve.gov"}],
        research_mode="market",
    )
    assert "## Market Intelligence Brief & Event Timeline" in md_mkt
    assert "## Impact Assessment & Probabilities" in md_mkt
    assert "## Source Credibility Weighting" in md_mkt

    # 3. Competitive mode
    md_comp = render_report_markdown(
        objective="Competitive Analysis",
        executive_answer="Challenger offers 40% lower TCO.",
        grounded_findings=[{"statement": "Pricing is usage-based.", "claim_ids": ["c1"]}],
        unverified_findings=[],
        claims=[{"id": "c1", "text": "Usage pricing model", "source_id": "s1", "status": "ACTIVE"}],
        sources=[{"id": "s1", "title": "Pricing Page", "domain": "competitor.com"}],
        research_mode="competitive",
    )
    assert "## Competitive Landscape Matrix" in md_comp
    assert "## Strategic Gap & Opportunity Analysis" in md_comp

    # 4. Technical mode
    md_tech = render_report_markdown(
        objective="Technical Architecture Evaluation",
        executive_answer="Rust backend delivers 3x throughput.",
        grounded_findings=[{"statement": "Sub-millisecond latency measured.", "claim_ids": ["c1"]}],
        unverified_findings=[],
        claims=[{"id": "c1", "text": "Latency is 0.8ms", "source_id": "s1", "status": "ACTIVE"}],
        sources=[{"id": "s1", "title": "Benchmark Doc", "domain": "docs.rs"}],
        research_mode="technical",
    )
    assert "## Technical Evaluation & Option Trade-Offs" in md_tech
    assert "## Implementation Recommendations & Migration Path" in md_tech
