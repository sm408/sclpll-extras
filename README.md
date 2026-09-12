# SCLPLL Extras

Public companion distribution for [SCLPL](https://github.com/sm408/sclpl-api): Visual Studio Code support, the SCLPLL language server, plugin packages, the bundled-function catalogue, and workflow assets.

SCLPL remains the language authority. This repository does **not** contain a second parser, formatter, or runtime. The extension and launcher use the installed `sclpl` package, so new syntax, formats, functions, connectors, and plugins remain consistent with the CLI.

## Install

1. Download and install `sclpll_language_server-1.0.1-py3-none-any.whl` from the [v1.0.1 release](https://github.com/sm408/sclpll-extras/releases/tag/v1.0.1):

   ```powershell
   py -3.12 -m pip install https://github.com/sm408/sclpll-extras/releases/download/v1.0.1/sclpll_language_server-1.0.1-py3-none-any.whl
   ```

2. Download `sclpl-language-tools-1.0.1.vsix` from the same release and install it with VS Code's **Extensions: Install from VSIX** command.

Open a `*.sclpll` workflow. Set `sclpl.pythonPath` only if VS Code selects a different Python environment.

The extension recognizes `.sclpll` only. It never executes workflows, scripts, HTTP calls, resource providers, or plugins as part of background editor analysis.

## Current catalog

| Folder | Purpose |
|---|---|
| [`vscode`](vscode/README.md) | VS Code extension source, TextMate grammar, snippets, and tests |
| [`language-server`](language-server/README.md) | Installable SCLPLL Python language server |
| [`plugins`](plugins/README.md) | Available plugin packages: `azure_blob` |
| [`functions`](functions/README.md) | Available bundled functions and ordinary Python-script functions |
| [`workflows`](workflows/README.md) | SCLPLL workflow library |
| [`docs`](docs/README.md) | Installation, security, and contributor documentation |

## Contributing

Keep DSL behavior in the core SCLPL repository. Contributions here should be editor UI, plugin/function packages, workflow assets, or documentation. Do not place credentials, tokens, connection strings, or production endpoints in this repository.
