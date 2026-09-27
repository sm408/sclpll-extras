# Feeds plugin

This package provides RSS and Atom connectors for SCLPL, plus a robots.txt check for polite fetching. It requires `defusedxml`, `httpx`, and an SCLPL installation compatible with the version declared in `pyproject.toml`.

Install from this directory:

```powershell
py -3.12 -m pip install .
```

## Connectors

| Connector | Does |
|---|---|
| `feeds.rss_read @response` | Parse a fetched RSS 2.0 or RSS 1.0 (RDF) feed into rows |
| `feeds.atom_read @response` | Parse a fetched Atom feed into rows |
| `feeds.feed_read url` | Fetch a feed over HTTP(S) and parse it as RSS or Atom, whichever it is |
| `feeds.robots_allowed url user_agent="sclpl"` | `true` if robots.txt lets `user_agent` fetch `url`; usable in `skip_if` |

Every row has the same shape whichever dialect it came from:

| Field | From |
|---|---|
| `title` | `title` (or `dc:title`) |
| `link` | `link`, or Atom's `rel="alternate"` link, resolved against the feed URL |
| `published` | `pubDate`, `dc:date`, Atom `published` or `updated`, as ISO 8601 UTC (`2026-09-01T09:30:00Z`); `null` if missing or unreadable, and a date without a zone is read as UTC |
| `summary` | `description`, `content:encoded`, Atom `summary` or `content`, as the feed gives it |
| `id` | `guid`, `rdf:about`, `dc:identifier` or Atom `id`, falling back to the link |
| `source` | The URL the feed was fetched from; for a raw body, the feed's own self or site link |

Rows carry links, never article bodies: the plugin does not scrape.

```text
@step fetch
  get https://example.com/feed.xml

@step items
  feeds.rss_read @fetch
```

Prefer an `http` step plus `feeds.rss_read` / `feeds.atom_read` when you want SCLPL's retry, cache, and rate limits: the core transport is not part of the public plugin API, so `feeds.feed_read` uses a plain HTTP client with a timeout (`timeout=10.0`) and a size cap (`max_bytes=5000000`), follows redirects, and fails on a 4xx or 5xx status.

## Safety

Feeds are parsed with `defusedxml`: a document that declares entities (including external entities that would read local files, or entity-expansion bombs) is rejected. A plain `DOCTYPE` with no entity declarations is accepted, and no DTD is ever fetched. Error messages never echo URL query strings or credentials.

`feeds.robots_allowed` fetches `/robots.txt` once per scheme and host and caches the answer for 24 hours in the running process. Following RFC 9309, a 4xx robots.txt means no rules (allowed), while a 5xx or network failure means everything is disallowed; that failure is retried after five minutes. Rule matching uses Python's `urllib.robotparser`.

The plugin declares the `network` capability, so `--deny-capability network` refuses to load it. Opening a workflow in VS Code does not fetch any feed.

## Tests

Tests use recorded fixtures and a mock transport; they never touch the network.

```powershell
py -3.12 -m pytest tests
```
