from __future__ import annotations

import tomllib
from inspect import signature
from pathlib import Path

import httpx
import pytest
from conftest import fixture
from sclpl.ext.api import StepFailed, ValidationError

import feeds
from feeds import feed_read, http, robots_allowed


def serve(routes: dict[str, httpx.Response], calls: list[str]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return routes.get(str(request.url), httpx.Response(404))

    http.TRANSPORT = httpx.MockTransport(handler)


def test_feed_read_fetches_detects_and_parses() -> None:
    calls: list[str] = []
    serve(
        {
            "https://example.com/feed": httpx.Response(
                301, headers={"location": "https://example.com/feed.atom"}
            ),
            "https://example.com/feed.atom": httpx.Response(200, content=fixture("atom.xml")),
        },
        calls,
    )
    rows = feed_read("https://example.com/feed")
    assert [row["id"] for row in rows] == ["urn:example:post:12", "urn:example:post:13"]
    assert {row["source"] for row in rows} == {"https://example.com/feed.atom"}  # after redirects
    assert calls == ["https://example.com/feed", "https://example.com/feed.atom"]


def test_feed_read_sends_the_user_agent() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["user-agent"])
        return httpx.Response(200, content=fixture("rss2.xml"))

    http.TRANSPORT = httpx.MockTransport(handler)
    assert len(feed_read("https://example.com/rss", user_agent="newsbot/1.0")) == 2
    assert seen == ["newsbot/1.0"]


def test_feed_read_refuses_errors_oversize_and_other_schemes() -> None:
    serve(
        {
            "https://example.com/big": httpx.Response(
                200, content=b"<rss>" + b" " * 2000 + b"</rss>"
            )
        },
        [],
    )
    with pytest.raises(StepFailed, match="status 404"):
        feed_read("https://example.com/missing?token=hidden")
    with pytest.raises(StepFailed, match="larger than 1000 bytes"):
        feed_read("https://example.com/big", max_bytes=1000)
    with pytest.raises(ValidationError, match="http"):
        feed_read("file:///etc/passwd")


def test_error_messages_do_not_echo_query_strings() -> None:
    serve({}, [])
    with pytest.raises(StepFailed) as raised:
        feed_read("https://user:pw@example.com/missing?token=hidden")
    assert "hidden" not in str(raised.value) and "pw" not in str(raised.value)


def test_network_failure_is_a_step_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow", request=request)

    http.TRANSPORT = httpx.MockTransport(handler)
    with pytest.raises(StepFailed, match="ConnectTimeout"):
        feed_read("https://example.com/feed")


def test_robots_allowed_respects_disallow_rules() -> None:
    serve(
        {"https://example.com/robots.txt": httpx.Response(200, content=fixture("robots.txt"))}, []
    )
    assert robots_allowed("https://example.com/news/feed.xml") is True
    assert robots_allowed("https://example.com/private/report") is False
    assert robots_allowed("https://example.com/tmp/x") is False
    assert robots_allowed("https://example.com/news", user_agent="badbot") is False
    assert robots_allowed("https://example.com/robots.txt", user_agent="badbot") is True


def test_robots_txt_is_fetched_once_per_host() -> None:
    calls: list[str] = []
    serve(
        {
            "https://example.com/robots.txt": httpx.Response(200, content=fixture("robots.txt")),
            "https://other.example/robots.txt": httpx.Response(
                200, content=b"User-agent: *\nDisallow: /"
            ),
        },
        calls,
    )
    assert robots_allowed("https://example.com/a")
    assert not robots_allowed("https://example.com/private/b")
    assert robots_allowed("https://EXAMPLE.com/c", user_agent="other")
    assert not robots_allowed("https://other.example/a")
    assert not robots_allowed("https://other.example/b")
    assert calls == ["https://example.com/robots.txt", "https://other.example/robots.txt"]


def test_robots_cache_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    serve({"https://example.com/robots.txt": httpx.Response(200, content=b"")}, calls)
    clock = [1000.0]
    monkeypatch.setattr(http.time, "monotonic", lambda: clock[0])
    robots_allowed("https://example.com/a")
    clock[0] += http.ROBOTS_TTL + 1
    robots_allowed("https://example.com/a")
    assert len(calls) == 2


def test_missing_robots_allows_and_unreachable_disallows() -> None:
    serve(
        {
            "https://gone.example/robots.txt": httpx.Response(404),
            "https://forbidden.example/robots.txt": httpx.Response(403),
            "https://down.example/robots.txt": httpx.Response(503),
        },
        [],
    )
    assert robots_allowed("https://gone.example/anything") is True
    assert robots_allowed("https://forbidden.example/anything") is True  # RFC 9309: any 4xx
    assert robots_allowed("https://down.example/anything") is False


def test_manifest_matches_the_code() -> None:
    manifest = tomllib.loads((Path(feeds.__file__).parents[1] / "plugin.toml").read_text("utf-8"))
    declared = {entry["name"]: entry["parameters"] for entry in manifest["connector"]}
    code = {
        "feeds.rss_read": feeds.rss_read,
        "feeds.atom_read": feeds.atom_read,
        "feeds.feed_read": feeds.feed_read,
        "feeds.robots_allowed": feeds.robots_allowed,
    }
    assert declared == {name: list(signature(call).parameters) for name, call in code.items()}
