"""Bounded HTTP collection via Tor SOCKS5 with remote DNS, no direct fallback."""
from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from http.client import HTTPConnection
import socket
import ssl
from typing import Callable
from urllib.parse import urlsplit, urljoin, quote_plus


@dataclass(frozen=True)
class CollectedPage:
    url: str
    status: str
    text: str = ""
    http_status: int = 0
    detail: str = ""
    links: list[dict[str, str]] = field(default_factory=list)


class EvidenceHTMLParser(HTMLParser):
    """Extract visible text and anchors, ignoring executable/style content."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.anchor: str | None = None
        self.label: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self.hidden += 1
        if tag == "a" and not self.hidden:
            self.anchor = dict(attrs).get("href")
            self.label = []

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"}:
            self.hidden = max(0, self.hidden - 1)
        if tag == "a" and self.anchor is not None:
            if len(self.links) < 1000:
                self.links.append((self.anchor, " ".join(self.label)))
            self.anchor = None
        if tag in {"p", "div", "br", "li", "h1", "h2"}:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)
            if self.anchor is not None:
                self.label.append(data)

    @property
    def text(self) -> str:
        return " ".join(" ".join(self.parts).split())


class TorHTTPTransport:
    """SOCKS5 domain-name CONNECT; .onion names never reach local DNS.

    The proxy must be provisioned by the operator. No automatic Tor installation,
    no proxy bypass, no credentials, no redirects followed by this transport.
    """

    def __init__(self, proxy_host: str | None = None, proxy_port: int | None = None) -> None:
        import os
        proxy_host = proxy_host or os.environ.get("TOR_SOCKS_HOST", "127.0.0.1")
        proxy_port = int(proxy_port or os.environ.get("TOR_SOCKS_PORT", "9050"))
        if not 1 <= proxy_port <= 65535:
            raise ValueError("invalid proxy port")
        self.proxy_host = proxy_host
        self.proxy_port = proxy_port

    def probe(self) -> bool:
        try:
            sock = socket.create_connection((self.proxy_host, self.proxy_port), timeout=2)
            try:
                sock.settimeout(2)
                sock.sendall(b"\x05\x01\x00")
                return self._read(sock, 2) == b"\x05\x00"
            finally:
                sock.close()
        except OSError:
            return False

    @staticmethod
    def _read(sock: socket.socket, size: int) -> bytes:
        data = b""
        while len(data) < size:
            part = sock.recv(size-len(data))
            if not part:
                raise ConnectionError("SOCKS proxy closed connection")
            data += part
        return data

    def __call__(self, url: str, timeout: float, max_bytes: int) -> tuple[int, dict[str, str], bytes]:
        parts = urlsplit(url)
        host = (parts.hostname or "").encode("idna")
        if not host or len(host) > 255 or parts.scheme not in {"http", "https"}:
            raise ValueError("invalid HTTP destination")
        port = parts.port or (443 if parts.scheme == "https" else 80)
        sock = socket.create_connection((self.proxy_host, self.proxy_port), timeout=timeout)
        connection = None
        try:
            sock.settimeout(timeout)
            sock.sendall(b"\x05\x01\x00")
            if self._read(sock, 2) != b"\x05\x00":
                raise ConnectionError("SOCKS5 unauthenticated negotiation refused")
            sock.sendall(b"\x05\x01\x00\x03" + bytes([len(host)]) + host + port.to_bytes(2, "big"))
            header = self._read(sock, 4)
            if header[:3] != b"\x05\x00\x00":
                raise ConnectionError("SOCKS5 CONNECT refused")
            length = {1: 4, 4: 16}.get(header[3])
            if header[3] == 3:
                length = self._read(sock, 1)[0]
            if length is None:
                raise ConnectionError("invalid SOCKS5 address type")
            self._read(sock, length + 2)
            if parts.scheme == "https":
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=parts.hostname)
            connection = HTTPConnection(parts.hostname, port, timeout=timeout)
            connection.sock = sock
            path = parts.path or "/"
            if parts.query:
                path += "?" + parts.query
            connection.request("GET", path, headers={"User-Agent": "FRIDAY-IntelX/1.0",
                "Accept": "text/html,text/plain", "Accept-Encoding": "identity"})
            response = connection.getresponse()
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise ValueError("response exceeds byte limit")
            return response.status, {k.lower(): v for k, v in response.getheaders()}, body
        finally:
            if connection is not None:
                connection.close()
            sock.close()


class ResearchCollector:
    """All redirects revalidate destination; failures are records, not empty success."""

    def __init__(self, policy, transport: Callable | None = None,
                 timeout: float = 15, max_bytes: int = 2*1024*1024,
                 max_redirects: int = 5) -> None:
        if not 0 < timeout <= 120 or not 1 <= max_bytes <= 10*1024*1024 or not 0 <= max_redirects <= 10:
            raise ValueError("invalid collection bounds")
        self.policy = policy
        self.transport = transport or TorHTTPTransport()
        self.timeout, self.max_bytes, self.max_redirects = timeout, max_bytes, max_redirects

    def fetch(self, url: str, allow_clearweb: bool = False) -> CollectedPage:
        current = url
        seen: set[str] = set()
        try:
            for hop in range(self.max_redirects + 1):
                current = self.policy.validate(current, allow_clearweb=allow_clearweb)
                if current in seen:
                    return CollectedPage(current, "redirect_loop")
                seen.add(current)
                status, headers, body = self.transport(current, self.timeout, self.max_bytes)
                headers = {k.lower(): v for k, v in headers.items()}
                if len(body) > self.max_bytes:
                    return CollectedPage(current, "too_large")
                if status in {301, 302, 303, 307, 308}:
                    location = headers.get("location")
                    if not location:
                        return CollectedPage(current, "error", http_status=status, detail="missing location")
                    current = urljoin(current, location)
                    continue
                if status != 200:
                    return CollectedPage(current, "blocked" if status in {401,403,429} else "error", http_status=status)
                kind = headers.get("content-type", "text/html").split(";")[0].strip()
                if kind not in {"text/html", "text/plain", "application/xhtml+xml"}:
                    return CollectedPage(current, "unsupported_content", http_status=status)
                if headers.get("content-encoding", "identity").lower() not in {"identity", ""}:
                    return CollectedPage(current, "unsupported_encoding", http_status=status)
                html = body.decode("utf-8", errors="replace")
                parser = EvidenceHTMLParser()
                if kind == "text/plain":
                    text = " ".join(html.split())
                else:
                    parser.feed(html)
                    text = parser.text
                page_links = []
                if kind != "text/plain":
                    for href, label in parser.links:
                        target = self.policy.extract_target(href, current, allow_clearweb=allow_clearweb)
                        clean_label = " ".join(label.split())[:120]
                        if target and clean_label:
                            page_links.append({"title": clean_label, "url": target})
                        if len(page_links) >= 20:
                            break
                return CollectedPage(current, "ok" if text else "empty", text, status, links=page_links)
            return CollectedPage(current, "redirect_limit")
        except ValueError as error:
            return CollectedPage(current, "refused", detail=str(error)[:160])
        except (OSError, ConnectionError, TimeoutError) as error:
            return CollectedPage(current, "unreachable", detail=type(error).__name__)

    def health(self) -> dict:
        probe = getattr(self.transport, "probe", None)
        if not callable(probe):
            return {"proxy_ready": None, "note": "injected transport; SOCKS probe unavailable"}
        return {"proxy_ready": bool(probe()), "proxy_host": getattr(self.transport, "proxy_host", "configured"),
                "proxy_port": getattr(self.transport, "proxy_port", None)}

    def search(self, endpoint: str, query: str, allow_clearweb: bool = False) -> dict:
        """Parse a configured onion engine HTML result page, including wrappers."""
        if endpoint.count("{query}") != 1:
            raise ValueError("engine URL must contain one {query} placeholder")
        url = self.policy.validate(endpoint.replace("{query}", quote_plus(query)))
        try:
            status, headers, body = self.transport(url, self.timeout, self.max_bytes)
            if status != 200:
                return {"engine": endpoint, "status": "failed", "results": []}
            if len(body) > self.max_bytes:
                return {"engine": endpoint, "status": "failed", "results": []}
            kind = next((v.split(";", 1)[0].strip().lower() for k, v in headers.items() if k.lower() == "content-type"), "text/html")
            if kind not in {"text/html", "application/xhtml+xml"}:
                return {"engine": endpoint, "status": "unsupported_content", "results": []}
            parser = EvidenceHTMLParser()
            parser.feed(body.decode("utf-8", errors="replace"))
            results = []
            for href, title in parser.links:
                target = self.policy.extract_target(href, url, allow_clearweb=allow_clearweb)
                if target:
                    results.append({"url": target, "title": " ".join(title.split())[:200]})
            return {"engine": endpoint, "status": "ok" if results else "empty", "results": results[:500]}
        except (OSError, ValueError, ConnectionError, TimeoutError):
            return {"engine": endpoint, "status": "failed", "results": []}
