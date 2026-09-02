"""INTELX HTTP Fetch Connector with strict SSRF, robots.txt, and rate limiting guards."""

import asyncio
import ipaddress
import logging
import socket
import time
import urllib.parse
import urllib.robotparser
from dataclasses import dataclass, field
from typing import Any

import httpx

from intelx.connectors.base import BaseConnector
from intelx.core.errors import (
    ContentSizeExceededError,
    RobotsDisallowedError,
    SSRFBlockedError,
    UnsupportedContentTypeError,
)
from intelx.core.settings import Settings, get_settings

logger = logging.getLogger(__name__)

ALLOWED_MIME_TYPES = {
    "text/html",
    "text/plain",
    "application/pdf",
    "application/json",
    "text/markdown",
    "text/csv",
}

BLOCKED_EXPLICIT_IPS = {
    "169.254.169.254",  # AWS/GCP/Azure Cloud Metadata
    "0.0.0.0",
    "::",
}


def is_ip_allowed(ip_str: str) -> bool:
    """Check if an IP address is safe for external requests (publicly routable)."""
    try:
        ip = ipaddress.ip_address(ip_str)
        if (
            str(ip) in BLOCKED_EXPLICIT_IPS
            or ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False
        return True
    except ValueError:
        return False


def validate_and_resolve_url(url: str) -> bool:
    """Validate that a URL does not resolve to a prohibited IP."""
    try:
        parsed = urllib.parse.urlparse(url)
        hostname = parsed.hostname or ""
        HttpFetchConnector.validate_ssrf(hostname, parsed.port or 80)
        return True
    except SSRFBlockedError:
        return False


@dataclass
class FetchResult:
    """Outcome of an HTTP fetch operation."""

    url: str
    final_url: str
    content: bytes
    content_type: str
    status_code: int
    robots_ok: bool = True
    headers: dict[str, str] = field(default_factory=dict)
    error: str | None = None


class HttpFetchConnector(BaseConnector):
    """Hardened HTTP fetch connector enforcing SSRF validation, robots.txt, and byte caps."""

    def __init__(
        self,
        settings: Settings | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        **kwargs: Any,
    ) -> None:
        cfg = settings or get_settings()
        super().__init__(
            name="http_fetch",
            capabilities=["fetch_html", "fetch_pdf", "fetch_raw"],
            required_credentials=[],
            classification="EXTERNAL_HTTP",
            settings=cfg,
            **kwargs,
        )
        self.settings = cfg
        self._transport = transport
        self._semaphore = asyncio.Semaphore(self.settings.MAX_CONCURRENT_FETCHES)
        self._domain_last_request: dict[str, float] = {}
        self._robots_cache: dict[str, tuple[urllib.robotparser.RobotFileParser, float]] = {}

    @classmethod
    def validate_ssrf(cls, hostname: str, port: int = 80) -> None:
        """Resolve hostname and reject any private, loopback, multicast, or metadata IPs."""
        try:
            ip_obj = ipaddress.ip_address(hostname)
            cls._check_ip_safety(ip_obj)
            return
        except ValueError:
            pass

        try:
            addr_info = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
        except socket.gaierror as e:
            logger.debug(f"DNS resolution failed for {hostname}: {e}")
            return

        for _, _, _, _, sockaddr in addr_info:
            ip_str = sockaddr[0]
            try:
                ip_obj = ipaddress.ip_address(ip_str)
                cls._check_ip_safety(ip_obj)
            except ValueError:
                continue

    @classmethod
    def _check_ip_safety(cls, ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
        """Verify individual IP address against security blacklist rules."""
        ip_str = str(ip)
        if ip_str in BLOCKED_EXPLICIT_IPS:
            raise SSRFBlockedError(
                f"SSRF violation: target resolved to prohibited IP '{ip_str}'",
                details={"ip": ip_str},
            )

        # Handle NAT64 / DNS64 Well-Known Prefix (RFC 6052: 64:ff9b::/96)
        if isinstance(ip, ipaddress.IPv6Address) and ip in ipaddress.IPv6Network("64:ff9b::/96"):
            embedded_ipv4 = ipaddress.IPv4Address(ip.packed[-4:])
            cls._check_ip_safety(embedded_ipv4)
            return

        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise SSRFBlockedError(
                f"SSRF violation: target resolved to prohibited IP '{ip_str}'",
                details={"ip": ip_str},
            )

    async def _check_robots(self, url: str, client: httpx.AsyncClient) -> bool:
        """Check robots.txt compliance cached for 1 hour."""
        if not self.settings.RESPECT_ROBOTS:
            return True

        parsed = urllib.parse.urlparse(url)
        domain = parsed.netloc.lower()
        now = time.time()

        if domain in self._robots_cache:
            parser, cache_time = self._robots_cache[domain]
            if now - cache_time < 3600:
                return parser.can_fetch(self.settings.USER_AGENT, url)

        robots_url = f"{parsed.scheme}://{domain}/robots.txt"
        rp = urllib.robotparser.RobotFileParser()
        try:
            self.validate_ssrf(parsed.hostname or domain, parsed.port or 80)
            res = await client.get(robots_url, timeout=5.0)
            if res.status_code == 200:
                rp.parse(res.text.splitlines())
            else:
                rp.allow_all = True
        except Exception:
            rp.allow_all = True

        self._robots_cache[domain] = (rp, now)
        return rp.can_fetch(self.settings.USER_AGENT, url)

    async def _apply_politeness(self, domain: str) -> None:
        """Enforce domain-specific politeness delay."""
        delay = self.settings.PER_DOMAIN_DELAY_S
        if delay <= 0:
            return

        now = time.time()
        last = self._domain_last_request.get(domain, 0.0)
        elapsed = now - last
        if elapsed < delay:
            await asyncio.sleep(delay - elapsed)
        self._domain_last_request[domain] = time.time()

    async def fetch(self, target: str, **kwargs: Any) -> FetchResult:
        """Fetch remote URL with SSRF checks, robots verification, and streaming size caps."""
        current_url = target
        max_redirects = 10

        async with self._semaphore:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=httpx.Timeout(self.settings.FETCH_TIMEOUT_S),
                headers={"User-Agent": self.settings.USER_AGENT},
                follow_redirects=False,
            ) as client:
                for redirect_hop in range(max_redirects):
                    parsed = urllib.parse.urlparse(current_url)
                    hostname = parsed.hostname or ""
                    if not hostname:
                        raise SSRFBlockedError(f"Invalid URL hostname: {current_url}")

                    # 1. Check connector domain policy
                    self.check_policy(hostname)

                    # 2. Enforce SSRF IP validation on EVERY redirect hop
                    port = parsed.port or (443 if parsed.scheme == "https" else 80)
                    self.validate_ssrf(hostname, port)

                    # 3. Check robots.txt on first hop
                    if redirect_hop == 0:
                        robots_allowed = await self._check_robots(current_url, client)
                        if not robots_allowed:
                            if kwargs.get("raise_on_robots", False):
                                raise RobotsDisallowedError(
                                    f"Access to {current_url} disallowed by robots.txt",
                                    details={"url": current_url},
                                )
                            return FetchResult(
                                url=target,
                                final_url=current_url,
                                content=b"",
                                content_type="text/html",
                                status_code=403,
                                robots_ok=False,
                                error="Disallowed by robots.txt",
                            )

                    # 4. Apply domain politeness delay
                    await self._apply_politeness(hostname)

                    # 5. Stream request to enforce MAX_PAGE_BYTES cap
                    async with client.stream("GET", current_url) as response:
                        if response.is_redirect and "Location" in response.headers:
                            next_url = urllib.parse.urljoin(
                                current_url, response.headers["Location"]
                            )
                            logger.debug(
                                f"Redirect {redirect_hop + 1}: {current_url} -> {next_url}"
                            )
                            current_url = next_url
                            continue

                        response.raise_for_status()

                        # 6. Validate Content-Type
                        raw_content_type = response.headers.get("content-type", "text/html")
                        mime_type = raw_content_type.split(";")[0].strip().lower()

                        if mime_type not in ALLOWED_MIME_TYPES:
                            err_msg = (
                                f"Refusing content-type '{mime_type}'. "
                                f"Allowed types: {ALLOWED_MIME_TYPES}"
                            )
                            raise UnsupportedContentTypeError(
                                err_msg, details={"mime_type": mime_type}
                            )

                        # 7. Check Content-Length if present
                        content_len = response.headers.get("content-length")
                        if content_len and int(content_len) > self.settings.MAX_PAGE_BYTES:
                            raise ContentSizeExceededError(
                                f"Size {content_len} exceeds MAX_PAGE_BYTES limit",
                                details={"size": int(content_len)},
                            )

                        # 8. Stream body with cumulative byte cap
                        accumulated = bytearray()
                        async for chunk in response.aiter_bytes():
                            accumulated.extend(chunk)
                            if len(accumulated) > self.settings.MAX_PAGE_BYTES:
                                raise ContentSizeExceededError(
                                    "Streamed body exceeded MAX_PAGE_BYTES limit",
                                    details={"bytes_received": len(accumulated)},
                                )

                        return FetchResult(
                            url=target,
                            final_url=current_url,
                            content=bytes(accumulated),
                            content_type=mime_type,
                            status_code=response.status_code,
                            robots_ok=True,
                            headers=dict(response.headers),
                        )

                raise SSRFBlockedError(f"Exceeded max redirects ({max_redirects}) for {target}")
