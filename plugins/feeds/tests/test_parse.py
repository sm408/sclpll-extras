from __future__ import annotations

import pytest
from conftest import fixture
from sclpl.ext.api import StepFailed, ValidationError

from feeds import atom_read, rss_read

URL = "https://example.com/feed"

EXPECTED = [
    {
        "title": "Release 1.2",
        "link": "https://example.com/posts/release-1-2",
        "published": "2026-09-01T09:30:00Z",
        "summary": "Faster parsing & fewer surprises.",
        "id": "urn:example:post:12",
        "source": URL,
    },
    {
        "title": "Security notice",
        "link": "https://example.com/posts/notice",
        "published": "2026-09-02T09:30:00Z",
        "summary": "Upgrade now.",
        "id": "urn:example:post:13",
        "source": URL,
    },
]


def response(name: str, **extra: object) -> dict[str, object]:
    """What an `http` step hands a workflow, with a recorded feed as the body."""
    return {"status": 200, "ok": True, "headers": {}, "body": fixture(name), "url": URL, **extra}


@pytest.mark.parametrize(
    ("reader", "name"),
    [
        (rss_read, "rss2.xml"),
        (rss_read, "rss2_namespaced.xml"),
        (rss_read, "rss1_rdf.xml"),
        (atom_read, "atom.xml"),
    ],
)
def test_every_dialect_parses_to_the_same_rows(reader, name) -> None:
    assert reader(response(name)) == EXPECTED


def test_text_bodies_work_as_well_as_bytes() -> None:
    body = fixture("rss2.xml").decode("utf-8")
    assert rss_read({"ok": True, "body": body, "url": URL}) == EXPECTED


def test_without_a_url_the_source_comes_from_the_feed() -> None:
    assert {row["source"] for row in rss_read(fixture("rss2.xml"))} == {"https://example.com/"}
    assert {row["source"] for row in atom_read(fixture("atom.xml"))} == {
        "https://example.com/feed.atom"
    }
    # Relative Atom links resolve against the feed's own address.
    assert atom_read(fixture("atom.xml"))[1]["link"] == "https://example.com/posts/notice"


def test_an_external_entity_is_rejected() -> None:
    with pytest.raises(ValidationError, match="entities or external references"):
        rss_read(response("xxe.xml"))


def test_entity_expansion_is_rejected() -> None:
    laughs = (
        b'<?xml version="1.0"?><!DOCTYPE rss [<!ENTITY a "lol"><!ENTITY b "&a;&a;&a;&a;">]>'
        b"<rss><channel><item><title>&b;</title></item></channel></rss>"
    )
    with pytest.raises(ValidationError, match="entities"):
        rss_read(laughs)


def test_a_plain_doctype_without_entities_is_still_a_feed() -> None:
    legacy = (
        b'<?xml version="1.0"?>\n'
        b'<!DOCTYPE rss PUBLIC "-//Netscape Communications//DTD RSS 0.91//EN"'
        b' "http://my.netscape.com/publish/formats/rss-0.91.dtd">\n'
        b'<rss version="0.91"><channel><link>https://example.com/</link>'
        b"<item><title>Old</title><link>https://example.com/old</link></item></channel></rss>"
    )
    [row] = rss_read(legacy)
    assert row["title"] == "Old"
    assert row["id"] == "https://example.com/old"  # no guid: the link stands in
    assert row["published"] is None


def test_the_wrong_reader_names_the_right_one() -> None:
    with pytest.raises(ValidationError, match="feeds.atom_read"):
        rss_read(response("atom.xml"))
    with pytest.raises(ValidationError, match="feeds.rss_read"):
        atom_read(response("rss2.xml"))


def test_html_and_json_are_not_feeds() -> None:
    with pytest.raises(ValidationError, match="root element is <html>"):
        rss_read(b"<html><body>Not a feed</body></html>")
    with pytest.raises(ValidationError, match="not well-formed"):
        rss_read("<rss><channel>")
    with pytest.raises(ValidationError, match="got dict"):
        rss_read({"ok": True, "body": {"items": []}})


def test_a_failed_request_is_not_parsed() -> None:
    with pytest.raises(StepFailed, match="status 503"):
        rss_read(response("rss2.xml", status=503, ok=False))


def test_unreadable_dates_become_none() -> None:
    body = (
        b"<rss><channel><item><title>x</title><pubDate>sometime soon</pubDate></item>"
        b"<item><title>y</title><pubDate>2026-09-01 09:30:00</pubDate></item></channel></rss>"
    )
    first, second = rss_read(body)
    assert first["published"] is None
    assert second["published"] == "2026-09-01T09:30:00Z"  # naive: read as UTC
