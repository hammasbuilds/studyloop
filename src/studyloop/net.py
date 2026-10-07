"""Fetch a web page for import without letting a URL reach the machine or its network.

The importer is a server-side fetch driven by a URL somebody typed (or a web page made them
submit), so it is an SSRF risk. Rules: http(s) only, no credentials in the URL, every address the
host name resolves to must be a public one, the connection is made to the address that was
checked (no second DNS lookup to rebind), every redirect is checked again, and the body, the
redirect count and the time are bounded.
"""

from __future__ import annotations

import http.client
import ipaddress
import os
import socket
import ssl
import time
from urllib.parse import urljoin, urlsplit

MAX_BYTES = 20 * 1024 * 1024
MAX_REDIRECTS = 5
TOTAL_TIMEOUT = 30.0
USER_AGENT = "StudyLoop/0.2 (personal study tool)"


class UnsafeURL(ValueError):
    """The URL points somewhere an import must never go, or is malformed."""


class FetchFailed(RuntimeError):
    pass


def _allow_private() -> bool:
    """``STUDYLOOP_ALLOW_PRIVATE_URLS=1`` lets an operator import from their own intranet or a
    local test server. Off by default; the web UI cannot turn it on."""
    return os.environ.get("STUDYLOOP_ALLOW_PRIVATE_URLS") == "1"


def _public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if _allow_private():
        return True
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        elif ip.sixtofour is not None:
            ip = ip.sixtofour
    return ip.is_global and not ip.is_multicast


def check_url_syntax(url: str) -> tuple[str, str, int, str]:
    """Return (scheme, host, port, path+query) or raise ``UnsafeURL``. No DNS lookup."""
    if len(url) > 2048 or any(ord(c) < 33 or ord(c) == 127 for c in url):
        raise UnsafeURL("that is not a valid web address")
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https"):
        raise UnsafeURL("the URL must start with http:// or https://")
    if parts.username is not None or parts.password is not None:
        raise UnsafeURL("web addresses with a user name or password are not accepted")
    try:
        host, port = parts.hostname, parts.port
    except ValueError as exc:
        raise UnsafeURL("that is not a valid web address") from exc
    if not host:
        raise UnsafeURL("that web address has no host")
    host = host.rstrip(".")
    if not _allow_private() and (host.lower() == "localhost" or host.lower().endswith((".localhost", ".local", ".internal"))):
        raise UnsafeURL("addresses on this computer or its network are not allowed")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and not _public(ip):
        raise UnsafeURL("addresses on this computer or its network are not allowed")
    scheme = parts.scheme.lower()
    target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    return scheme, host, port or (443 if scheme == "https" else 80), target


def resolve_public(host: str, port: int) -> list[str]:
    """Resolve ``host`` and return its addresses, refusing if ANY of them is not public."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise FetchFailed(f"could not look up {host}") from exc
    addrs = []
    for info in infos:
        addr = info[4][0].split("%")[0]
        if not _public(ipaddress.ip_address(addr)):
            raise UnsafeURL("addresses on this computer or its network are not allowed")
        if addr not in addrs:
            addrs.append(addr)
    if not addrs:
        raise FetchFailed(f"could not look up {host}")
    return addrs


def _connect(scheme: str, host: str, port: int, addr: str, timeout: float):
    sock = socket.create_connection((addr, port), timeout=timeout)
    if scheme == "https":
        sock = ssl.create_default_context().wrap_socket(sock, server_hostname=host)
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    conn.sock = sock  # the already-checked connection; http.client will not dial again
    return conn


def fetch_page(url: str, *, resolver=resolve_public) -> tuple[bytes, str, str | None]:
    """GET ``url`` and return (body, final_url, content_type). Raises UnsafeURL / FetchFailed."""
    deadline = time.monotonic() + TOTAL_TIMEOUT
    for _ in range(MAX_REDIRECTS + 1):
        scheme, host, port, target = check_url_syntax(url)
        addrs = resolver(host, port)
        left = deadline - time.monotonic()
        if left <= 0:
            raise FetchFailed("the page took too long")
        conn = None
        last: Exception | None = None
        for addr in addrs:
            try:
                conn = _connect(scheme, host, port, addr, min(10.0, left))
                break
            except OSError as exc:
                last = exc
        if conn is None:
            raise FetchFailed(f"could not connect to {host}: {last}")
        try:
            default = (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
            conn.putrequest("GET", target, skip_host=True, skip_accept_encoding=True)
            conn.putheader("Host", host if default else f"{host}:{port}")
            conn.putheader("User-Agent", USER_AGENT)
            conn.putheader("Accept", "text/html,*/*;q=0.5")
            conn.putheader("Accept-Encoding", "identity")
            conn.putheader("Connection", "close")
            conn.endheaders()
            resp = conn.getresponse()
            if resp.status in (301, 302, 303, 307, 308):
                loc = resp.getheader("Location")
                if not loc:
                    raise FetchFailed("redirect without a destination")
                url = urljoin(url, loc)
                continue
            if resp.status != 200:
                raise FetchFailed(f"{host} returned HTTP {resp.status}")
            ctype = resp.getheader("Content-Type")
            if ctype and "html" not in ctype.lower() and "xml" not in ctype.lower() \
                    and "text/plain" not in ctype.lower():
                raise FetchFailed(f"that address returned {ctype.split(';')[0]!r}, not a web page")
            body = bytearray()
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                body += chunk
                if len(body) > MAX_BYTES:
                    raise FetchFailed(f"the page is larger than {MAX_BYTES // (1024 * 1024)} MB")
                if time.monotonic() > deadline:
                    raise FetchFailed("the page took too long")
            return bytes(body), url, ctype
        except (OSError, http.client.HTTPException) as exc:
            raise FetchFailed(f"could not fetch the page: {exc}") from exc
        finally:
            conn.close()
    raise FetchFailed("too many redirects")
