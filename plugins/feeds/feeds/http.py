"""The two network touches: fetching a feed, and fetching robots.txt once per host.

Both use a plain ``httpx`` client with a timeout and a byte cap. SCLPL's own transport
(retry, cache, rate limits) is not part of the public plugin API, so a workflow that
needs those should fetch with an ``http`` step and hand the result to
``feeds.rss_read`` / ``feeds.atom_read`` instead of calling ``feeds.feed_read``.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from urllib.parse import SplitResult, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from sclpl.ext.api import StepFailed, ValidationError

#: Tests swap in an ``httpx.MockTransport``; ``None`` means the real network.
TRANSPORT: httpx.BaseTransport | None = None

FEED_ACCEPT = (
    "application/rss+xml, application/atom+xml, application/rdf+xml,"
    " application/xml;q=0.9, text/xml;q=0.9, */*;q=0.1"
)

#: RFC 9309 asks crawlers to parse at least the first 500 KiB of a robots.txt.
ROBOTS_MAX_BYTES = 500 * 1024
#: How long an answer is reused. RFC 9309 says not to cache beyond 24 hours; an
#: unreachable robots.txt is retried sooner so a brief outage does not stick.
ROBOTS_TTL = 24 * 3600.0
ROBOTS_FAILURE_TTL = 300.0

_ROBOTS: dict[tuple[str, str], tuple[float, RobotFileParser]] = {}
_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class Fetched:
    status: int
    content: bytes
    url: str


def fetch(
    url: str,
    *,
    timeout: float,
    user_agent: str,
    max_bytes: int,
    accept: str = "*/*",
    truncate: bool = False,
) -> Fetched:
    """GET ``url``. Bodies past ``max_bytes`` fail, or are cut short with ``truncate``."""
    _check_url(url)
    headers = {"User-Agent": user_agent, "Accept": accept}
    try:
        with (
            httpx.Client(
                transport=TRANSPORT, timeout=timeout, follow_redirects=True, headers=headers
            ) as client,
            client.stream("GET", url) as response,
        ):
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > max_bytes:
                    if not truncate:
                        raise StepFailed(
                            f"{display(url)} is larger than {max_bytes} bytes",
                            remedies=["raise max_bytes if this feed is really that large"],
                        )
                    chunks.append(chunk[: max_bytes - (size - len(chunk))])
                    break
                chunks.append(chunk)
            return Fetched(response.status_code, b"".join(chunks), str(response.url))
    except httpx.HTTPError as error:
        raise StepFailed(
            f"could not fetch {display(url)}: {type(error).__name__}",
            remedies=["check the URL and your network", "raise timeout for a slow server"],
        ) from error


def robots_for(url: str, *, timeout: float, user_agent: str) -> RobotFileParser:
    """The parsed robots.txt for ``url``'s host, fetched at most once per TTL."""
    parts = _check_url(url)
    key = (
        parts.scheme.lower(),
        (parts.hostname or "").lower() + (f":{parts.port}" if parts.port else ""),
    )
    now = time.monotonic()
    with _LOCK:
        cached = _ROBOTS.get(key)
        if cached is not None and cached[0] > now:
            return cached[1]
    rules = RobotFileParser()
    ttl = ROBOTS_TTL
    try:
        got = fetch(
            f"{key[0]}://{key[1]}/robots.txt",
            timeout=timeout,
            user_agent=user_agent,
            max_bytes=ROBOTS_MAX_BYTES,
            accept="text/plain, */*;q=0.1",
            truncate=True,
        )
    except StepFailed:
        got = None
    if got is not None and 200 <= got.status < 300:
        rules.parse(got.content.decode("utf-8", errors="replace").splitlines())
    elif got is not None and 400 <= got.status < 500:
        # RFC 9309 2.3.1.3: an unavailable robots.txt (any 4xx) means no rules.
        rules.parse([])
    else:
        # RFC 9309 2.3.1.4: unreachable (5xx, network error) means assume full disallow.
        rules.parse(["User-agent: *", "Disallow: /"])
        ttl = ROBOTS_FAILURE_TTL
    with _LOCK:
        _ROBOTS[key] = (now + ttl, rules)
    return rules


def clear_robots_cache() -> None:
    with _LOCK:
        _ROBOTS.clear()


def display(url: str) -> str:
    """A URL fit for a message: no userinfo, no query string (either may hold a secret)."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{host}{port}{parts.path}"


def _check_url(url: str) -> SplitResult:
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ValidationError(
            f"expected an absolute http(s) URL, got scheme {parts.scheme or '(none)'!r}",
            remedies=["pass an absolute URL such as https://example.com/feed.xml"],
        )
    return parts
