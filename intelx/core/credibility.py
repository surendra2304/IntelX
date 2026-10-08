"""INTELX Domain Source Credibility Scoring and Hierarchy Engine."""

import re
from pathlib import Path
from urllib.parse import unquote, urlparse

from intelx.core.enums import ResearchMode, normalize_research_mode


class SourceCredibilityScorer:
    """Evaluates domain and source authority based on domain-specific hierarchies."""

    # Security Domain Hierarchy (MITRE > CISA > Vendor Advisories > Research Blogs > Forums)
    SECURITY_HIERARCHY = [
        (
            1.00,
            "MITRE / CVE Authority",
            [
                r"mitre\.org",
                r"attack\.mitre\.org",
                r"cve\.org",
                r"cve\.mitre\.org",
            ],
        ),
        (
            0.90,
            "CISA / NIST Standards Body",
            [
                r"cisa\.gov",
                r"nvd\.nist\.gov",
                r"nist\.gov",
                r"us-cert\.gov",
                r"cyber\.gov\.au",
                r"ncsc\.gov\.uk",
            ],
        ),
        (
            0.80,
            "Vendor Security Advisory",
            [
                r"msrc\.microsoft\.com",
                r"microsoft\.com",
                r"cisco\.com",
                r"redhat\.com",
                r"github\.com/advisories",
                r"cert\.org",
                r"oracle\.com",
                r"ubuntu\.com",
                r"debian\.org",
                r"apple\.com",
                r"google\.com/about/appsecurity",
            ],
        ),
        (
            0.65,
            "Security Research Publication",
            [
                r"krebsonsecurity\.com",
                r"schneier\.com",
                r"bleepingcomputer\.com",
                r"unit42\.paloaltonetworks\.com",
                r"mandiant\.com",
                r"googleprojectzero\.blogspot\.com",
                r"threatpost\.com",
                r"darkreading\.com",
                r"thehackernews\.com",
                r"securityweek\.com",
            ],
        ),
        (
            0.30,
            "Community / Unverified Forum",
            [
                r"reddit\.com",
                r"twitter\.com",
                r"x\.com",
                r"pastebin\.com",
                r"hackernews",
                r"forum",
            ],
        ),
    ]

    # Market Domain Hierarchy (SEC Filings > Central Banks > Major Financial Press > Analyst Reports > Social)
    MARKET_HIERARCHY = [
        (
            1.00,
            "SEC Regulatory Filing",
            [
                r"sec\.gov",
                r"edgar\.sec\.gov",
                r"data\.sec\.gov",
            ],
        ),
        (
            0.95,
            "Central Bank / Financial Authority",
            [
                r"federalreserve\.gov",
                r"ecb\.europa\.eu",
                r"bis\.org",
                r"bankofengland\.co\.uk",
                r"treasury\.gov",
                r"cftc\.gov",
                r"finra\.org",
                r"imf\.org",
                r"worldbank\.org",
            ],
        ),
        (
            0.80,
            "Major Financial Publication",
            [
                r"bloomberg\.com",
                r"reuters\.com",
                r"ft\.com",
                r"wsj\.com",
                r"cnbc\.com",
                r"economist\.com",
                r"barrons\.com",
                r"marketwatch\.com",
            ],
        ),
        (
            0.70,
            "Institutional Equity Research",
            [
                r"morningstar\.com",
                r"spglobal\.com",
                r"moodys\.com",
                r"fitchratings\.com",
                r"goldmansachs\.com",
                r"morganstanley\.com",
                r"jpmorgan\.com",
                r"blackrock\.com",
            ],
        ),
        (
            0.25,
            "Social Media / Retail Sentiment",
            [
                r"reddit\.com",
                r"stocktwits\.com",
                r"twitter\.com",
                r"x\.com",
                r"seekingalpha\.com",
                r"fool\.com",
            ],
        ),
    ]

    # Technical Domain Hierarchy (Official Docs > RFCs > Peer-Reviewed > Conference Talks > Blogs)
    TECHNICAL_HIERARCHY = [
        (
            1.00,
            "Official Documentation",
            [
                r"docs\.python\.org",
                r"docs\.rust-lang\.org",
                r"docs\.kernel\.org",
                r"docs\.postgresql\.org",
                r"python\.org",
                r"rust-lang\.org",
                r"kernel\.org",
                r"w3\.org",
                r"developer\.mozilla\.org",
                r"golang\.org",
                r"nodejs\.org",
                r"react\.dev",
                r"kubernetes\.io",
                r"postgresql\.org",
                r"apache\.org",
                r"linuxfoundation\.org",
            ],
        ),
        (
            0.95,
            "Standards Body / RFC",
            [
                r"rfc-editor\.org",
                r"ietf\.org",
                r"iso\.org",
                r"ieee\.org",
                r"open-std\.org",
                r"ansi\.org",
            ],
        ),
        (
            0.90,
            "Peer-Reviewed Academic Corpus",
            [
                r"arxiv\.org",
                r"nature\.com",
                r"acm\.org",
                r"sciencedirect\.com",
                r"springer\.com",
                r"science\.org",
                r"biorxiv\.org",
            ],
        ),
        (
            0.75,
            "Technical Conference / Industry Books",
            [
                r"usenix\.org",
                r"blackhat\.com",
                r"defcon\.org",
                r"oreilly\.com",
                r"packtpub\.com",
                r"infoq\.com",
            ],
        ),
        (
            0.50,
            "Community Developer Blog",
            [
                r"medium\.com",
                r"dev\.to",
                r"stackoverflow\.com",
                r"stackexchange\.com",
                r"substack\.com",
                r"hashnode\.dev",
                r"reddit\.com",
            ],
        ),
    ]

    # Competitive / General Domain Hierarchy
    COMPETITIVE_HIERARCHY = [
        (
            0.95,
            "Official Regulatory / Patent Filing",
            [
                r"uspto\.gov",
                r"wipo\.int",
                r"sec\.gov",
                r"gov\.uk",
            ],
        ),
        (
            0.90,
            "Primary Corporate Disclosure",
            [
                r"company\.com",
            ],
        ),
        (
            0.80,
            "Industry Press & Benchmark",
            [
                r"techcrunch\.com",
                r"venturebeat\.com",
                r"theverge\.com",
                r"wired\.com",
                r"forbes\.com",
            ],
        ),
        (
            0.60,
            "Review Aggregator & Comparison",
            [
                r"g2\.com",
                r"capterra\.com",
                r"trustradius\.com",
                r"gartner\.com",
            ],
        ),
        (
            0.30,
            "User Forum & Social Discussion",
            [
                r"reddit\.com",
                r"twitter\.com",
                r"x\.com",
                r"quora\.com",
            ],
        ),
    ]

    @classmethod
    def score_source(
        cls,
        location: str,
        mode_or_hint: str | ResearchMode | None = None,
    ) -> tuple[float, str]:
        """Compute credibility score [0.10 - 1.00] and descriptive tier label for a source."""
        mode = normalize_research_mode(mode_or_hint)
        loc_clean = location.lower().strip()

        # Local paths are trusted corpus entries only when the location itself is
        # local, never when a remote URL merely contains a familiar path segment.
        try:
            parsed = urlparse(loc_clean)
        except ValueError:
            parsed = None
        source_path = (parsed.path.replace("\\", "/") if parsed else "").lower()
        if parsed and (parsed.scheme == "file" or not parsed.scheme):
            # Normalize dot segments, percent-encoding, and existing symlinks before
            # deciding whether a local file is part of the trusted fixture corpus.
            source_path = Path(unquote(source_path)).resolve().as_posix().lower()
        path_parts = [part for part in source_path.strip("/").split("/") if part]
        local_file_uri = bool(
            parsed and parsed.scheme == "file" and parsed.netloc in ("", "localhost")
        )
        local_path = bool(parsed and not parsed.scheme and not parsed.netloc)
        is_verified_corpus_path = any(
            path_parts[index : index + 2] in (["data", "uploads"], ["evals", "fixtures"])
            for index in range(max(0, len(path_parts) - 1))
        )
        if (local_file_uri or local_path) and is_verified_corpus_path:
            return 0.85, "Verified Local Corpus"

        # Extract only the normalized hostname for authority matching. A trusted
        # hostname appearing in a path, username, or lookalike suffix is not authority.
        try:
            parsed = urlparse(loc_clean if "://" in loc_clean else f"//{loc_clean}")
            domain_target = (parsed.hostname or "").rstrip(".").encode("idna").decode("ascii")
            source_path = parsed.path.lower()
        except (UnicodeError, ValueError):
            domain_target = ""
            source_path = ""

        # Select domain hierarchy
        if mode == ResearchMode.SECURITY_RESEARCH:
            hierarchy = cls.SECURITY_HIERARCHY
            default_score = 0.50
            default_label = "General Security Source"
        elif mode == ResearchMode.MARKET_RESEARCH:
            hierarchy = cls.MARKET_HIERARCHY
            default_score = 0.50
            default_label = "General Financial Source"
        elif mode == ResearchMode.TECHNICAL_RESEARCH:
            hierarchy = cls.TECHNICAL_HIERARCHY
            default_score = 0.60
            default_label = "General Technical Documentation"
        elif mode == ResearchMode.COMPETITIVE_RESEARCH:
            hierarchy = cls.COMPETITIVE_HIERARCHY
            default_score = 0.55
            default_label = "General Market Source"
        else:
            hierarchy = cls.TECHNICAL_HIERARCHY
            default_score = 0.50
            default_label = "General Web Source"

        for score, label, patterns in hierarchy:
            for pat in patterns:
                host_pattern, separator, path_pattern = pat.partition("/")
                host_re = rf"(?:[a-z0-9-]+\.)*{host_pattern}"
                if not domain_target or not re.fullmatch(host_re, domain_target, re.IGNORECASE):
                    continue
                if separator:
                    required_path = [part for part in path_pattern.strip("/").split("/") if part]
                    actual_path = [part for part in source_path.strip("/").split("/") if part]
                    if actual_path[: len(required_path)] != required_path:
                        continue
                return score, label

        return default_score, default_label

    @classmethod
    def get_credibility_adjustment(cls, score: float) -> float:
        """Compute bounded adjustment factor [-0.10, +0.10] for composite confidence."""
        # 0.70 is the neutral midpoint: >0.70 gives a boost, <0.70 gives a deduction
        raw_bonus = (score - 0.70) * 0.20
        return round(max(-0.10, min(0.10, raw_bonus)), 4)
