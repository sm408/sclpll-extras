# ADR 0009 - Budget the editor language service

## Status

Accepted.

## Decision

Add `sclpl/language/` as its own 1,200-line budget and raise the total source budget
from 21,700 to 22,900 lines.

## Rationale

The language service is an editor-only boundary around existing parser, formatter, IR,
registry, and plugin-manifest APIs. Keeping it in `run/` would blur the runtime/editor
dependency direction; leaving it unbudgeted would bypass the repository's growth gate.
The dedicated budget retains the same CI enforcement as every other package and keeps
normal CLI/runtime users free of the optional LSP dependency.
