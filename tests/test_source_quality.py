"""Regression tests for source authority and freshness scoring."""

import math

import pytest

from intelx.connectors.source_quality import SourceQuality


@pytest.mark.parametrize(
    "url",
    [
        "https://sec.gov.attacker.example/report",
        "https://example.sec.gov.attacker.example/report",
        "https://nature.com.attacker.example/paper",
        "https://notgov.example/report",
    ],
)
def test_untrusted_host_suffix_does_not_receive_primary_authority_bonus(url):
    score = SourceQuality().score(url, "report", "snippet", set())
    assert score.authority == pytest.approx(0.55)


def test_trusted_domain_and_its_subdomains_receive_authority_bonus():
    scorer = SourceQuality()
    for url in ("https://sec.gov/filing", "https://www.sec.gov/filing", "https://nature.com/paper"):
        assert scorer.score(url, "title", "snippet", set()).authority == pytest.approx(0.85)


@pytest.mark.parametrize("age", [math.nan, math.inf, -math.inf, -1.0, "not-a-number"])
def test_invalid_publication_age_receives_no_freshness_credit(age):
    score = SourceQuality().score("https://example.com", "title", "snippet", set(), age)
    assert score.freshness == 0.0


def test_missing_publication_age_is_unknown_not_perfectly_fresh():
    score = SourceQuality().score("https://example.com", "title", "snippet", set())
    assert score.freshness == 0.5


def test_low_quality_penalty_requires_a_domain_label():
    scorer = SourceQuality()
    low_quality = scorer.score("https://forums.example.com", "title", "", set())
    ordinary = scorer.score("https://myforums.example.com", "title", "", set())
    assert low_quality.authority == pytest.approx(0.35)
    assert ordinary.authority == pytest.approx(0.55)
