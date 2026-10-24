"""
IntelX/paper_analyzer.py — IntelX Research Paper Analyzer.

Extends IntelX's capabilities with:
1. Paper Parsing: extract structure from research papers
2. Citation Analysis: analyze citation networks
3. Methodology Assessment: evaluate research methodology
4. Finding Extraction: extract key findings from papers
5. Paper Comparison: compare multiple papers
6. Literature Review: generate literature reviews from multiple papers
"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PaperSection:
    """A section in a research paper."""
    name: str  # abstract, introduction, methodology, results, conclusion
    content: str
    word_count: int = 0
    key_points: list[str] = field(default_factory=list)


@dataclass
class ResearchPaper:
    """A research paper."""
    paper_id: str
    title: str
    authors: list[str]
    year: int
    venue: str
    abstract: str
    sections: dict[str, PaperSection] = field(default_factory=dict)
    references: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    methodology: str = ""


@dataclass
class CitationNetwork:
    """A citation network."""
    paper_id: str
    cited_by: list[str]
    cited_papers: list[str]
    total_citations: int
    influential_citations: int
    h_index: float
    impact_factor: float


@dataclass
class PaperComparison:
    """Comparison between papers."""
    papers: list[str]
    common_topics: list[str]
    differences: list[str]
    methodology_comparison: str
    findings_comparison: str
    recommendation: str


class PaperAnalyzer:
    """Research paper analysis engine."""

    def __init__(self):
        self._papers: dict[str, ResearchPaper] = {}
        self._citation_networks: dict[str, CitationNetwork] = {}

    # ── Paper Parsing ───────────────────────────────────────────────────────

    def parse_paper(
        self,
        title: str,
        text: str,
        authors: list[str] | None = None,
        year: int | None = None,
        venue: str = "",
    ) -> ResearchPaper:
        """Parse a research paper into structured sections."""
        paper_id = hashlib.md5(
            f"{title}:{time.time()}".encode()
        ).hexdigest()[:12]

        paper = ResearchPaper(
            paper_id=paper_id,
            title=title,
            authors=authors or [],
            year=year or 2024,
            venue=venue,
            abstract="",
        )

        # Extract sections
        sections = self._extract_sections(text)

        for name, content in sections.items():
            word_count = len(content.split())
            key_points = self._extract_key_points(content)

            section = PaperSection(
                name=name,
                content=content,
                word_count=word_count,
                key_points=key_points,
            )

            paper.sections[name] = section

        # Extract abstract
        if "abstract" in paper.sections:
            paper.abstract = paper.sections["abstract"].content[:500]

        # Extract references
        paper.references = self._extract_references(text)

        # Extract keywords
        paper.keywords = self._extract_keywords(text)

        # Extract findings
        paper.findings = self._extract_findings(paper)

        # Extract methodology
        if "methodology" in paper.sections:
            paper.methodology = paper.sections["methodology"].content[:200]

        self._papers[paper_id] = paper
        return paper

    def _extract_sections(self, text: str) -> dict[str, str]:
        """Extract sections from paper text."""
        sections = {}

        # Common section headers
        patterns = {
            "abstract": r"(?:^|\n)\s*(?:\d+\.?)?\s*Abstract\s*(?:\n|$)",
            "introduction": r"(?:^|\n)\s*(?:\d+\.?)?\s*Introduction\s*(?:\n|$)",
            "methodology": r"(?:^|\n)\s*(?:\d+\.?)?\s*(?:Methodology|Methods|Materials and Methods)\s*(?:\n|$)",
            "results": r"(?:^|\n)\s*(?:\d+\.?)?\s*(?:Results|Findings)\s*(?:\n|$)",
            "conclusion": r"(?:^|\n)\s*(?:\d+\.?)?\s*(?:Conclusion|Discussion)\s*(?:\n|$)",
        }

        # Find section boundaries
        positions = {}
        for name, pattern in patterns.items():
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                positions[name] = match.start()

        # Sort by position
        sorted_sections = sorted(positions.items(), key=lambda x: x[1])

        # Extract content
        for i, (name, pos) in enumerate(sorted_sections):
            end = sorted_sections[i + 1][1] if i + 1 < len(sorted_sections) else len(text)
            sections[name] = text[pos:end].strip()

        return sections

    def _extract_key_points(self, content: str) -> list[str]:
        """Extract key points from section content."""
        points = []

        # Split into sentences
        sentences = re.split(r'[.!?]+', content)

        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) > 30 and len(sentence) < 300:
                # Check if it contains important keywords
                important = ["important", "significant", "key", "crucial", "essential", "novel", "new"]
                if any(kw in sentence.lower() for kw in important):
                    points.append(sentence)

        return points[:5]

    def _extract_references(self, text: str) -> list[str]:
        """Extract references from paper."""
        # Look for [1], [2], etc.
        references = re.findall(r'\[(\d+)\]', text)
        return list(set(references))[:20]

    def _extract_keywords(self, text: str) -> list[str]:
        """Extract keywords from paper."""
        # Look for bold or italic text (simplified)
        words = text.lower().split()
        word_freq: dict[str, int] = {}

        for word in words:
            if len(word) > 5 and not word.isdigit():
                word_freq[word] = word_freq.get(word, 0) + 1

        keywords = sorted(word_freq.items(), key=lambda x: -x[1])[:10]
        return [w for w, _ in keywords]

    def _extract_findings(self, paper: ResearchPaper) -> list[str]:
        """Extract key findings from a paper."""
        findings = []

        if "results" in paper.sections:
            findings.extend(paper.sections["results"].key_points)

        if "conclusion" in paper.sections:
            findings.extend(paper.sections["conclusion"].key_points)

        return findings[:10]

    # ── Citation Analysis ────────────────────────────────────────────────────

    def analyze_citations(
        self,
        paper_id: str,
        cited_by_count: int = 0,
        cited_papers_count: int = 0,
    ) -> CitationNetwork:
        """Analyze citation network for a paper."""
        # Simulated citation data
        cited_by = [f"paper_{i}" for i in range(min(cited_by_count, 20))]
        cited_papers = [f"paper_{i}" for i in range(min(cited_papers_count, 20))]

        # Calculate h-index (simplified)
        h_index = min(cited_by_count, cited_papers_count) ** 0.5

        # Impact factor
        impact = max(0.1, cited_by_count / max(1, cited_papers_count))

        network = CitationNetwork(
            paper_id=paper_id,
            cited_by=cited_by,
            cited_papers=cited_papers,
            total_citations=cited_by_count,
            influential_citations=max(0, int(cited_by_count * 0.1)),
            h_index=h_index,
            impact_factor=impact,
        )

        self._citation_networks[paper_id] = network
        return network

    # ── Methodology Assessment ───────────────────────────────────────────────

    def assess_methodology(self, paper: ResearchPaper) -> dict[str, Any]:
        """Assess the methodology of a paper."""
        methodology = paper.methodology.lower()

        score = 0.0
        criteria = []

        # Check for experimental design
        if any(kw in methodology for kw in ["experiment", "randomized", "controlled", "double-blind"]):
            score += 20
            criteria.append("Has experimental design")

        # Check for statistical analysis
        if any(kw in methodology for kw in ["statistical", "p-value", "confidence interval", "t-test", "anova"]):
            score += 20
            criteria.append("Uses statistical analysis")

        # Check for sample size
        if any(kw in methodology for kw in ["sample", "participants", "subjects", "n ="]):
            score += 15
            criteria.append("Reports sample information")

        # Check for replication
        if any(kw in methodology for kw in ["replication", "reproducibility", "repeat"]):
            score += 15
            criteria.append("Addresses reproducibility")

        # Check for limitations
        if any(kw in methodology for kw in ["limitation", "bias", "confounding"]):
            score += 15
            criteria.append("Addresses limitations")

        # Check for ethics
        if any(kw in methodology for kw in ["ethic", "consent", "approval", "irb"]):
            score += 10
            criteria.append("Addresses ethical considerations")

        # Check for controls
        if any(kw in methodology for kw in ["control", "baseline", "comparison"]):
            score += 5
            criteria.append("Has control group")

        # Determine quality
        if score >= 70:
            quality = "strong"
        elif score >= 50:
            quality = "moderate"
        elif score >= 30:
            quality = "weak"
        else:
            quality = "poor"

        return {
            "paper_id": paper.paper_id,
            "score": score,
            "quality": quality,
            "criteria_met": criteria,
            "recommendations": self._methodology_recommendations(score),
        }

    def _methodology_recommendations(self, score: float) -> list[str]:
        """Generate methodology recommendations."""
        recs = []
        if score < 70:
            recs.append("Strengthen experimental design")
        if score < 60:
            recs.append("Include statistical analysis")
        if score < 50:
            recs.append("Report sample size and characteristics")
        if score < 40:
            recs.append("Address reproducibility")
        return recs

    # ── Paper Comparison ────────────────────────────────────────────────────

    def compare_papers(self, paper_ids: list[str]) -> PaperComparison:
        """Compare multiple papers."""
        papers = [self._papers.get(pid) for pid in paper_ids]
        papers = [p for p in papers if p]

        if len(papers) < 2:
            return PaperComparison(
                papers=paper_ids,
                common_topics=[],
                differences=[],
                methodology_comparison="Not enough papers to compare",
                findings_comparison="Not enough papers to compare",
                recommendation="Need at least 2 papers",
            )

        # Find common topics
        all_keywords = set()
        for p in papers:
            all_keywords.update(p.keywords)

        common_topics = list(all_keywords)[:10]

        # Find differences
        differences = []
        for p in papers:
            differences.append(f"{p.title}: {len(p.findings)} findings")

        # Compare methodologies
        methodology_text = "\n".join(p.methodology for p in papers if p.methodology)

        # Compare findings
        all_findings = [f for p in papers for f in p.findings]
        findings_comparison = f"Total findings: {len(all_findings)}"

        # Recommendation
        if len(common_topics) > 5:
            recommendation = f"Papers share strong thematic overlap - consider meta-analysis"
        else:
            recommendation = "Papers cover diverse topics - broader literature review recommended"

        return PaperComparison(
            papers=[p.paper_id for p in papers],
            common_topics=common_topics,
            differences=differences,
            methodology_comparison=methodology_text[:200],
            findings_comparison=findings_comparison,
            recommendation=recommendation,
        )

    # ── Literature Review ────────────────────────────────────────────────────

    def generate_literature_review(
        self,
        topic: str,
        paper_ids: list[str],
    ) -> dict[str, Any]:
        """Generate a literature review from multiple papers."""
        papers = [self._papers.get(pid) for pid in paper_ids]
        papers = [p for p in papers if p]

        if not papers:
            return {"topic": topic, "status": "NO_PAPERS"}

        # Collect all findings
        all_findings = []
        for p in papers:
            all_findings.extend(p.findings)

        # Group findings by theme
        themes: dict[str, list[str]] = {}
        for finding in all_findings:
            # Simple theme assignment
            for kw in finding.lower().split():
                if len(kw) > 5:
                    themes.setdefault(kw, []).append(finding)

        # Generate review sections
        review = {
            "topic": topic,
            "papers_analyzed": len(papers),
            "key_themes": [t for t in themes if len(themes[t]) > 1][:10],
            "summary": f"Analysis of {len(papers)} papers on {topic} reveals ",
            "findings": all_findings[:20],
            "gaps": self._identify_gaps(papers),
            "future_directions": self._future_directions(papers),
        }

        return review

    def _identify_gaps(self, papers: list[ResearchPaper]) -> list[str]:
        """Identify research gaps."""
        gaps = []

        # Check for limited sample sizes
        if any("small" in p.methodology.lower() or "limited" in p.methodology.lower() for p in papers):
            gaps.append("Limited sample sizes across studies")

        # Check for lack of replication
        if not any("replicat" in p.methodology.lower() for p in papers):
            gaps.append("Lack of replication studies")

        # Check for missing demographics
        if not any("diversity" in p.methodology.lower() or "demographic" in p.methodology.lower() for p in papers):
            gaps.append("Limited demographic diversity in studies")

        return gaps

    def _future_directions(self, papers: list[ResearchPaper]) -> list[str]:
        """Suggest future research directions."""
        directions = [
            "Longitudinal studies to assess long-term effects",
            "Cross-cultural replication of findings",
            "Integration with emerging technologies",
            "Meta-analytic synthesis of existing findings",
        ]

        return directions[:3]

    # ── Reporting ──────────────────────────────────────────────────────────

    def get_paper_report(self) -> dict[str, Any]:
        """Generate a paper analysis report."""
        return {
            "total_papers": len(self._papers),
            "total_citation_networks": len(self._citation_networks),
            "avg_paper_sections": sum(len(p.sections) for p in self._papers.values()) / max(1, len(self._papers)),
        }
