# VS Code extension

This is the thin VS Code client for SCLPLL. It supplies immediate TextMate coloring, snippets, language configuration, commands, and an LSP client. All semantic behavior comes from `python -m sclpll_language_server` in the selected Python environment.

## Develop or package

```powershell
py -3.12 -m pip install -e ../language-server
npm ci
npm run lint
npm run compile
npm test
npm run package
```

Use `F5` from this folder for an Extension Development Host, or install the generated `.vsix` through VS Code. The extension recognizes `.sclpll`, not JSON workflow files.

See [`../docs/vscode.md`](../docs/vscode.md) for setup and troubleshooting.
