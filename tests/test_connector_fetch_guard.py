"""Regression tests for fail-closed outbound target validation."""

import socket

import pytest

from intelx.connectors.fetch_guard import SSRFBlocked, resolve_and_validate, safe_target
from intelx.connectors.web import HttpFetchConnector, validate_and_resolve_url
from intelx.core.errors import SSRFBlockedError


def test_dns_resolution_failure_is_blocked(monkeypatch):
    def fail_dns(*_args, **_kwargs):
        raise socket.gaierror("temporary resolver failure")

    monkeypatch.setattr("intelx.connectors.fetch_guard.socket.getaddrinfo", fail_dns)

    with pytest.raises(SSRFBlocked, match="DNS resolution failure"):
        resolve_and_validate("research.example")


def test_empty_dns_answer_is_blocked(monkeypatch):
    monkeypatch.setattr("intelx.connectors.fetch_guard.socket.getaddrinfo", lambda *_a, **_k: [])

    with pytest.raises(SSRFBlocked, match="no addresses"):
        resolve_and_validate("research.example")


def test_every_dns_answer_must_be_globally_routable(monkeypatch):
    answers = [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 0)),
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("127.0.0.1", 0)),
    ]
    monkeypatch.setattr(
        "intelx.connectors.fetch_guard.socket.getaddrinfo", lambda *_a, **_k: answers
    )

    with pytest.raises(SSRFBlocked, match="127.0.0.1"):
        resolve_and_validate("mixed.example")


def test_http_fetch_connector_propagates_dns_failures_as_ssrf_blocks(monkeypatch):
    def fail_dns(*_args, **_kwargs):
        raise socket.gaierror("resolver unavailable")

    monkeypatch.setattr("intelx.connectors.fetch_guard.socket.getaddrinfo", fail_dns)

    with pytest.raises(SSRFBlockedError, match="DNS resolution failure"):
        HttpFetchConnector.validate_ssrf("unresolvable.example")


def test_safe_target_rejects_non_http_and_url_credentials_before_dns():
    with pytest.raises(SSRFBlocked, match="prohibited URL scheme"):
        safe_target("file:///etc/passwd")
    with pytest.raises(SSRFBlocked, match="user information"):
        safe_target("https://trusted.example@attacker.example/article")


def test_url_validator_rejects_malformed_targets_and_uses_https_port(monkeypatch):
    ports = []

    def public_dns(_host, port, **_kwargs):
        ports.append(port)
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", port))]

    monkeypatch.setattr("intelx.connectors.fetch_guard.socket.getaddrinfo", public_dns)
    assert validate_and_resolve_url("https://research.example/article") is True
    assert ports == [443]

    def unexpected_dns(*_args, **_kwargs):
        pytest.fail("invalid URL syntax should be rejected before DNS resolution")

    monkeypatch.setattr("intelx.connectors.fetch_guard.socket.getaddrinfo", unexpected_dns)
    invalid_targets = (
        "ftp://research.example/article",
        "http://user:pass@research.example/article",
        "https://research.example:invalid/article",
        "https://research.example:0/article",
    )
    assert all(not validate_and_resolve_url(target) for target in invalid_targets)
