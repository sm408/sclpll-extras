# Migrated from sclpl-api

These files were sitting uncommitted in the `sclpl-api` working directory
(never part of its git history) as a near-byte-identical duplicate of what
already lives properly in this repo (`language-server/`, `vscode/`). Moved
here on 2026-09-13 rather than deleted outright, in case any of the renamed
imports (`sclpl.language.*` instead of `sclpll_language_server`) or the
tweaked pip-install error message are worth diffing against before this
folder is deleted for good.

Safe to delete once reviewed -- nothing here is referenced by sclpl-api or by
this repo's own `language-server`/`vscode` packages.
