# SCLPLL Extras

Public companion resources for [SCLPL](https://github.com/sm408/sclpl-api): Visual Studio Code support, a language-server launcher, safe plugin examples, ordinary Python-function examples, and validated workflow samples.

SCLPL remains the language authority. This repository does **not** contain a second parser, formatter, or runtime. The extension and launcher use the installed `sclpl` package, so new syntax, formats, functions, connectors, and plugins remain consistent with the CLI.

## Start here

1. Install the language server: `py -3.12 -m pip install -e language-server`.
2. Build the extension: `cd vscode; npm ci; npm run package`.
3. In VS Code, run **Extensions: Install from VSIX** and choose the generated file.
4. Open a `*.sclpll` workflow. Set `sclpl.pythonPath` if VS Code selects a different Python environment.

The extension recognizes `.sclpll` only. It never executes workflows, scripts, HTTP calls, resource providers, or plugins as part of background editor analysis.

## Repository map

| Folder | Purpose |
|---|---|
| [`vscode`](vscode/README.md) | VS Code extension source, TextMate grammar, snippets, and tests |
| [`language-server`](language-server/README.md) | Small `sclpll-language-server` launcher for the canonical Python server |
| [`plugins`](plugins/README.md) | Installable provider/plugin examples |
| [`functions`](functions/README.md) | Ordinary Python script-function examples |
| [`workflows`](workflows/README.md) | Copyable SCLPLL workflow examples |
| [`docs`](docs/README.md) | Installation, security, and contributor documentation |

## Contributing

Keep DSL behavior in the core SCLPL repository. Contributions here should be editor UI, plugin/function examples, workflow samples, or documentation. Do not place credentials, tokens, connection strings, or production endpoints in examples.
