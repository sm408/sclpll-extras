"""RSS and Atom feeds as rows, and a robots.txt check for polite fetching.

Rows carry links, never article bodies: this plugin does not scrape. Every row has the
same shape whatever the feed dialect -- ``title``, ``link``, ``published`` (ISO 8601
UTC), ``summary``, ``id`` and ``source``.

Only ``sclpl.ext.api`` is imported from the core.
"""

from __future__ import annotations

from typing import Any

from sclpl.ext.api import StepFailed, connector

from .http import FEED_ACCEPT, display, fetch, robots_for
from .parse import document, parse_feed


def register() -> None:
    """Nothing to do after load: importing the module registered the connectors."""


@connector("feeds.rss_read")
def rss_read(response: Any) -> list[dict[str, Any]]:
    """Parse a fetched RSS 2.0 or RSS 1.0 feed into rows.

    Pass an http step's result (or the raw body). Fetching with an http step keeps
    SCLPL's retry, cache and rate limits in play.
    """
    body, url = document(response)
    return parse_feed(body, kind="rss", source=url)


@connector("feeds.atom_read")
def atom_read(response: Any) -> list[dict[str, Any]]:
    """Parse a fetched Atom feed into rows."""
    body, url = document(response)
    return parse_feed(body, kind="atom", source=url)


@connector("feeds.feed_read", lane="thread")
def feed_read(
    url: str,
    *,
    timeout: float = 10.0,
    user_agent: str = "sclpl",
    max_bytes: int = 5_000_000,
) -> list[dict[str, Any]]:
    """Fetch a feed over HTTP(S) and parse it as RSS or Atom, whichever it is."""
    got = fetch(
        url, timeout=timeout, user_agent=user_agent, max_bytes=max_bytes, accept=FEED_ACCEPT
    )
    if got.status >= 400:
        raise StepFailed(
            f"{display(url)} returned status {got.status}",
            remedies=["check the URL", "fetch with an http step to get retries"],
        )
    return parse_feed(got.content, kind="auto", source=got.url)


@connector("feeds.robots_allowed", lane="thread")
def robots_allowed(url: str, user_agent: str = "sclpl", *, timeout: float = 10.0) -> bool:
    """Whether robots.txt lets ``user_agent`` fetch ``url``. Cached per host."""
    return robots_for(url, timeout=timeout, user_agent=user_agent).can_fetch(user_agent, url)
