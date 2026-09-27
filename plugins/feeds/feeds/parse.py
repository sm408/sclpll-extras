"""Turn an RSS 2.0, RSS 1.0 (RDF) or Atom document into rows of one fixed shape.

Every row has exactly ``title``, ``link``, ``published``, ``summary``, ``id`` and
``source``, whichever dialect it came from, so a workflow never has to branch on the
feed format. ``published`` is an ISO 8601 UTC timestamp (``2026-09-27T12:00:00Z``) or
``None`` when the feed gives no date or one that cannot be read.

Parsing goes through ``defusedxml`` with entity declarations and external references
forbidden: a feed is untrusted input, and an entity is how a hostile one reads local
files or expands itself into gigabytes.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Literal
from urllib.parse import urljoin
from xml.etree.ElementTree import Element, ParseError

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import fromstring
from sclpl.ext.api import StepFailed, ValidationError

Kind = Literal["rss", "atom", "auto"]

ATOM = "{http://www.w3.org/2005/Atom}"
RSS1 = "{http://purl.org/rss/1.0/}"
RDF = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}"
DC = "{http://purl.org/dc/elements/1.1/}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}"

FIELDS = ("title", "link", "published", "summary", "id", "source")


def document(response: Any) -> tuple[str | bytes, str | None]:
    """The XML body and the URL it came from, out of whatever the workflow passed.

    Accepts an ``http`` step result (``{"status", "ok", "body", "url", ...}``) or the
    raw body as text or bytes.
    """
    url: str | None = None
    body: Any = response
    if isinstance(response, Mapping):
        if response.get("ok") is False:
            raise StepFailed(
                f"the feed request returned status {response.get('status')}",
                remedies=["check the URL", "gate the step on @response.ok"],
            )
        body = response.get("body")
        url = response.get("url") if isinstance(response.get("url"), str) else None
    if isinstance(body, bytearray):
        body = bytes(body)
    if isinstance(body, str):
        return body.lstrip(), url
    if isinstance(body, bytes):
        return body.lstrip(b" \t\r\n"), url
    raise ValidationError(
        f"expected a feed body as text or bytes, got {type(body).__name__}",
        remedies=["pass the result of an http step: feeds.rss_read @fetch"],
    )


def parse_feed(
    body: str | bytes, *, kind: Kind = "auto", source: str | None = None
) -> list[dict[str, Any]]:
    """Parse one feed document into rows. ``kind`` refuses the other dialect."""
    try:
        root = fromstring(body, forbid_dtd=False, forbid_entities=True, forbid_external=True)
    except DefusedXmlException as error:
        raise ValidationError(
            "refusing a feed that declares entities or external references"
            f" ({type(error).__name__})",
            remedies=["feeds are parsed without DTD entities; this document is unsafe to expand"],
        ) from error
    except ParseError as error:
        raise ValidationError(
            f"the feed is not well-formed XML: {error}",
            remedies=["check that the URL returns a feed and not an HTML page"],
        ) from error

    found: Kind
    if root.tag == f"{ATOM}feed":
        found = "atom"
    elif root.tag in ("rss", f"{RDF}RDF"):
        found = "rss"
    else:
        raise ValidationError(
            f"not an RSS or Atom feed: the root element is <{_local(root.tag)}>",
            remedies=["check that the URL returns a feed and not an HTML page"],
        )
    if kind != "auto" and kind != found:
        other = "feeds.atom_read" if found == "atom" else "feeds.rss_read"
        raise ValidationError(
            f"expected an {kind.upper() if kind == 'rss' else 'Atom'} feed, got {found}",
            remedies=[f"use {other}, or feeds.feed_read, which detects the format"],
        )
    return _atom(root, source) if found == "atom" else _rss(root, source)


def _rss(root: Element, source: str | None) -> list[dict[str, Any]]:
    if root.tag == "rss":
        channel = root.find("channel")
        items = channel.findall("item") if channel is not None else []
        home = _text(channel, "link") if channel is not None else None
        ns = ""
    else:  # RSS 1.0: items are siblings of the channel, all in the RSS 1.0 namespace.
        channel = root.find(f"{RSS1}channel")
        items = root.findall(f"{RSS1}item")
        home = _text(channel, f"{RSS1}link") if channel is not None else None
        ns = RSS1
    base = source or home
    rows = []
    for item in items:
        link = _resolve(base, _text(item, f"{ns}link"))
        guid = _text(item, "guid") if not ns else item.get(f"{RDF}about")
        rows.append(
            _row(
                title=_text(item, f"{ns}title") or _text(item, f"{DC}title"),
                link=link,
                published=_date(_text(item, "pubDate") or _text(item, f"{DC}date")),
                summary=_text(item, f"{ns}description") or _text(item, f"{CONTENT}encoded"),
                id=guid or _text(item, f"{DC}identifier") or link,
                source=base,
            )
        )
    return rows


def _atom(root: Element, source: str | None) -> list[dict[str, Any]]:
    base = source or _atom_link(root, None, rel="self") or _atom_link(root, None)
    rows = []
    for entry in root.findall(f"{ATOM}entry"):
        link = _atom_link(entry, base)
        rows.append(
            _row(
                title=_text(entry, f"{ATOM}title"),
                link=link,
                published=_date(_text(entry, f"{ATOM}published") or _text(entry, f"{ATOM}updated")),
                summary=_text(entry, f"{ATOM}summary") or _text(entry, f"{ATOM}content"),
                id=_text(entry, f"{ATOM}id") or link,
                source=base,
            )
        )
    return rows


def _atom_link(element: Element, base: str | None, *, rel: str = "alternate") -> str | None:
    for link in element.findall(f"{ATOM}link"):
        if link.get("rel", "alternate") == rel and link.get("href"):
            return _resolve(base, link.get("href"))
    return None


def _row(**values: Any) -> dict[str, Any]:
    return {name: values[name] for name in FIELDS}


def _text(element: Element | None, path: str) -> str | None:
    if element is None:
        return None
    found = element.find(path)
    if found is None:
        return None
    # `itertext` covers Atom's type="xhtml" content, which arrives as child elements.
    text = "".join(found.itertext()).strip()
    return text or None


def _resolve(base: str | None, link: str | None) -> str | None:
    if not link:
        return None
    return urljoin(base, link) if base else link


def _date(value: str | None) -> str | None:
    """RFC 822 (RSS) or RFC 3339 (Atom, Dublin Core) to ISO 8601 UTC; else None."""
    if not value:
        return None
    moment: datetime | None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        try:
            moment = parsedate_to_datetime(value)
        except (TypeError, ValueError, IndexError):
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]
