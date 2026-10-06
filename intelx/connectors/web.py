"""INTELX HTTP Fetch Connector with strict SSRF, robots.txt, and rate limiting guards."""

import asyncio
import ipaddress
import logging
import time
import urllib.parse
import urllib.robotparser
from dataclasses import dataclass, field
from typing import Any

import httpx

from intelx.connectors.base import BaseConnector
from intelx.connectors.fetch_guard import SSRFBlocked, resolve_and_validate
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
    "application/rss+xml",
    "application/atom+xml",
    "application/xml",
    "text/xml",
    "text/markdown",
    "text/csv",
}

BLOCKED_EXPLICIT_IPS = {
    "169.254.169.254",  # AWS/GCP/Azure Cloud Metadata
    "0.0.0.0",
    "::",
}


def is_ip_allowed(ip_str: str) -> bool:
    """Check if an IP address is safe for external requests (globally routable)."""
    try:
        ip = ipaddress.ip_address(ip_str)
        if isinstance(ip, ipaddress.IPv6Address):
            if ip.ipv4_mapped is not None:
                ip = ip.ipv4_mapped
            elif ip in ipaddress.IPv6Network("64:ff9b::/96"):
                ip = ipaddress.IPv4Address(ip.packed[-4:])
        return str(ip) not in BLOCKED_EXPLICIT_IPS and ip.is_global
    except ValueError:
        return False


def validate_and_resolve_url(url: str) -> bool:
    """Validate HTTP(S) URL syntax and reject targets that resolve to unsafe IPs."""
    try:
        parsed = urllib.parse.urlsplit(url)
        hostname = parsed.hostname or ""
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not hostname
            or parsed.username is not None
            or parsed.password is not None
            or "%" in hostname
        ):
            return False
        explicit_port = parsed.port
        if explicit_port == 0:
            return False
        port = (
            explicit_port
            if explicit_port is not None
            else (443 if parsed.scheme.lower() == "https" else 80)
        )
        HttpFetchConnector.validate_ssrf(hostname, port)
        return True
    except (SSRFBlockedError, ValueError):
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
    def validate_ssrf(cls, hostname: str, port: int = 80) -> list[str]:
        """Resolve hostname and reject DNS errors or any non-public resolved address."""
        try:
            return resolve_and_validate(hostname, port=port)
        except SSRFBlocked as exc:
            logger.debug("SSRF validation blocked %s: %s", hostname, exc)
            raise SSRFBlockedError(
                f"SSRF violation: {exc}",
                details={"host": hostname},
            ) from exc

    def _validated_stream(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        timeout: float | None = None,
    ) -> Any:
        """Build a request pinned to a previously validated public DNS address.

        The original hostname remains in Host and TLS SNI, while the socket (or
        proxy CONNECT target) uses the IP that passed SSRF validation. This
        closes the gap where a second DNS lookup could resolve to a private IP.
        """
        parsed = urllib.parse.urlsplit(url)
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname or ""
        if scheme not in {"http", "https"} or not hostname or "%" in hostname:
            raise SSRFBlockedError(f"Invalid or prohibited URL: {url}")
        try:
            explicit_port = parsed.port
        except ValueError as exc:
            raise SSRFBlockedError(f"Invalid URL port: {url}") from exc
        if explicit_port == 0:
            raise SSRFBlockedError(f"Invalid URL port: {url}")
        port = explicit_port if explicit_port is not None else (443 if scheme == "https" else 80)
        resolved_addresses = self.validate_ssrf(hostname, port)
        try:
            destination = ipaddress.ip_address(resolved_addresses[0])
        except (IndexError, ValueError) as exc:
            raise SSRFBlockedError(f"No valid public address resolved for {hostname}") from exc

        destination_host = (
            f"[{destination.compressed}]"
            if isinstance(destination, ipaddress.IPv6Address)
            else destination.compressed
        )
        pinned_url = urllib.parse.urlunsplit(
            (scheme, f"{destination_host}:{port}", parsed.path or "/", parsed.query, "")
        )

        try:
            original_ip = ipaddress.ip_address(hostname)
        except ValueError:
            try:
                original_host = hostname.encode("idna").decode("ascii")
            except UnicodeError as exc:
                raise SSRFBlockedError(f"Invalid target hostname: {hostname}") from exc
            extensions = {"sni_hostname": original_host} if scheme == "https" else {}
        else:
            original_host = (
                f"[{original_ip.compressed}]"
                if isinstance(original_ip, ipaddress.IPv6Address)
                else original_ip.compressed
            )
            extensions = {}

        host_header = f"{original_host}:{explicit_port}" if explicit_port else original_host
        options: dict[str, Any] = {
            "headers": {"Host": host_header},
            "extensions": extensions,
        }
        if timeout is not None:
            options["timeout"] = timeout
        return client.stream("GET", pinned_url, **options)

    @classmethod
    def _check_ip_safety(cls, ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
        """Verify an individual resolved address is globally routable."""
        if not is_ip_allowed(str(ip)):
            raise SSRFBlockedError(
                f"SSRF violation: target resolved to prohibited IP '{ip}'",
                details={"ip": str(ip)},
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
            async with self._validated_stream(client, robots_url, timeout=5.0) as res:
                if res.status_code == 200:
                    body = await res.aread()
                    rp.parse(body.decode("utf-8", errors="replace").splitlines())
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
        requested_max_bytes = kwargs.get("max_bytes", self.settings.MAX_PAGE_BYTES)
        if (
            not isinstance(requested_max_bytes, int)
            or isinstance(requested_max_bytes, bool)
            or requested_max_bytes < 1
        ):
            raise ValueError("max_bytes must be a positive integer")
        max_bytes = min(requested_max_bytes, self.settings.MAX_PAGE_BYTES)

        async with self._semaphore:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=httpx.Timeout(self.settings.FETCH_TIMEOUT_S),
                headers={"User-Agent": self.settings.USER_AGENT},
                follow_redirects=False,
                trust_env=True,
            ) as client:
                for redirect_hop in range(max_redirects):
                    parsed = urllib.parse.urlparse(current_url)
                    hostname = parsed.hostname or ""
                    if (
                        parsed.scheme.lower() not in ("http", "https")
                        or not hostname
                        or parsed.username is not None
                        or parsed.password is not None
                    ):
                        raise SSRFBlockedError(f"Invalid or prohibited URL: {current_url}")
                    try:
                        parsed_port = parsed.port
                    except ValueError as exc:
                        raise SSRFBlockedError(f"Invalid URL port: {current_url}") from exc

                    # 1. Check connector domain policy
                    self.check_policy(hostname)

                    # 2. Enforce SSRF IP validation on EVERY redirect hop
                    if parsed_port == 0:
                        raise SSRFBlockedError(f"Invalid URL port: {current_url}")
                    port = (
                        parsed_port
                        if parsed_port is not None
                        else (443 if parsed.scheme.lower() == "https" else 80)
                    )
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
                    async with self._validated_stream(client, current_url) as response:
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
                        if content_len and int(content_len) > max_bytes:
                            raise ContentSizeExceededError(
                                f"Size {content_len} exceeds the MAX_PAGE_BYTES/fetch limit of {max_bytes} bytes",
                                details={"size": int(content_len), "limit": max_bytes},
                            )

                        # 8. Stream body with cumulative byte cap
                        accumulated = bytearray()
                        async for chunk in response.aiter_bytes():
                            accumulated.extend(chunk)
                            if len(accumulated) > max_bytes:
                                raise ContentSizeExceededError(
                                    f"Streamed body exceeded the MAX_PAGE_BYTES/fetch limit of {max_bytes} bytes",
                                    details={
                                        "bytes_received": len(accumulated),
                                        "limit": max_bytes,
                                    },
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
