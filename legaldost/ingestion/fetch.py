"""Controlled download of registered source documents.

* HTTPS only, host must be on ``INGEST_ALLOWED_DOMAINS`` (checked again on every redirect hop).
* Size-limited streaming download.
* Minimum interval between requests to the same host.
Respect each site's terms of use; the allowlist is not a statement that bulk scraping is allowed.
"""

from __future__ import annotations

import ssl
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx

from legaldost import __version__

USER_AGENT = f"LegalDostIngest/{__version__} (+manual curated ingestion; contact: operator)"
_last_request: dict[str, float] = {}


class FetchError(Exception):
    pass


@dataclass
class FetchResult:
    url: str
    data: bytes
    content_type: str | None


def check_url(url: str, allowed_domains: list[str]) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise FetchError(f"only https URLs are allowed: {url}")
    host = (parsed.hostname or "").lower()
    if host not in {d.lower() for d in allowed_domains}:
        raise FetchError(f"host {host!r} is not in INGEST_ALLOWED_DOMAINS")


def _ssl_context() -> ssl.SSLContext | bool:
    """Verify certificates against the operating-system trust store when available.

    Some Indian government hosts serve incomplete chains that the OS store can complete but the
    bundled certifi store cannot. Verification is never disabled.
    """
    try:
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:  # pragma: no cover
        return True


def fetch(
    url: str,
    allowed_domains: list[str],
    max_bytes: int,
    min_interval: float = 2.0,
    timeout: float = 60.0,
    client: httpx.Client | None = None,
) -> FetchResult:
    own_client = client is None
    http = client or httpx.Client(timeout=timeout, headers={"User-Agent": USER_AGENT}, verify=_ssl_context())
    try:
        current = url
        for _hop in range(6):
            check_url(current, allowed_domains)
            host = urlparse(current).hostname or ""
            wait = min_interval - (time.monotonic() - _last_request.get(host, 0.0))
            if wait > 0:
                time.sleep(wait)
            _last_request[host] = time.monotonic()
            try:
                with http.stream("GET", current, follow_redirects=False) as resp:
                    if resp.is_redirect:
                        location = resp.headers.get("location")
                        if not location:
                            raise FetchError("redirect without location")
                        current = urljoin(current, location)
                        continue
                    if resp.status_code != 200:
                        raise FetchError(f"HTTP {resp.status_code} for {current}")
                    declared = resp.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > max_bytes:
                        raise FetchError(f"document larger than limit ({declared} bytes)")
                    chunks, total = [], 0
                    for chunk in resp.iter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise FetchError("document larger than limit")
                        chunks.append(chunk)
                    return FetchResult(current, b"".join(chunks), resp.headers.get("content-type"))
            except httpx.HTTPError as exc:
                raise FetchError(f"{type(exc).__name__}: {exc}") from exc
        raise FetchError("too many redirects")
    finally:
        if own_client:
            http.close()
