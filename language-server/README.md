# SCLPLL language server

This package exposes `sclpll-language-server` and contains the editor-neutral analysis and LSP transport. It delegates parsing, formatting, registries, plugin discovery, and project metadata to the installed core SCLPL package. That keeps DSL semantics in one place.

Install it with the same environment that has editor-enabled SCLPL:

```powershell
py -3.12 -m pip install .
sclpll-language-server --stdio
```

The VS Code extension launches `python -m sclpll_language_server --stdio`; install this package in the same environment it selects.
