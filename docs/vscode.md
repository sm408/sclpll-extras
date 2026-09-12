# Visual Studio Code support

This repository ships the VS Code extension source tree in `vscode`. It recognizes only
`.sclpll` files as **SCLPLL**; JSON workflows intentionally remain JSON.

## Install

Install the release wheel, then install the release VSIX using VS Code's **Extensions: Install from VSIX** command. No Node build is needed for users.

```powershell
py -3.12 -m pip install https://github.com/sm408/sclpll-extras/releases/download/v1.0.1/sclpll_language_server-1.0.1-py3-none-any.whl
```

## Develop

Install the optional server dependency in the same Python environment as SCLPL:

```powershell
py -3.12 -m pip install -e language-server
cd vscode
npm ci
npm run package
```

Install the generated `.vsix` with VS Code's **Install from VSIX** command. The
extension has no Marketplace publishing configuration and does not publish anything.

The client selects `sclpl.pythonPath` first, then the workspace's selected Python
setting when available, a workspace `.venv`, then `python3` on Unix or `py` on
Windows. It does not require the Microsoft Python extension. Before startup it checks
that the selected interpreter imports both `sclpl` and `pygls`. If that check fails,
TextMate coloring, comments, bracket handling, and snippets continue to work; the
extension shows one install/retry/select-Python message.

## What it provides

- lexical highlighting and semantic tokens using normal VS Code theme scopes;
- passive diagnostics, completion, hover, signatures, definition, references,
  rename, outline, workspace symbols, formatting, folding, quick fixes, and CodeLens;
- built-in callable metadata plus static plugin-manifest vocabulary; plugin code is
  never imported just because a document was opened or changed;
- safe project names such as declared auth-profile names, without copying profile
  secrets, endpoints, or plugin-setting values into editor responses;
- snippets for workflow directives, HTTP/function/Python steps, controls, modes, and
  output writers;
- explicit **SCLPL: Validate/Run/Explain/Format/Show Workflow Graph** commands.

For a plugin callable to show its precise signature without being imported, declare
optional `signature` and `parameters` fields on its `[[function]]`, `[[connector]]`,
or `[[verb]]` manifest contribution. Otherwise the editor safely presents the callable
as `name(...)`. A malformed plugin manifest produces one `SCLPL700` warning and leaves
the rest of the language service available.

`Format Document` uses the Python SCLPL parser/emitter. If parsing fails it makes no
edit. Set VS Code's `editor.formatOnSave` for `[sclpll]` yourself if wanted; the
extension deliberately defaults it to off.

The minimal extension settings are `sclpl.pythonPath`, `sclpl.trace.server`,
`sclpl.diagnostics.enable`, and `sclpl.semanticHighlighting.enable`. Changing one
restarts the server when needed; disabling diagnostics clears editor squiggles and
disabling semantic highlighting leaves the TextMate grammar as the lexical fallback.

## Security and troubleshooting

Background language features are static: they never run workflow steps or Python
scripts, send HTTP requests, touch resource providers, acquire leases, publish output,
or reveal secrets. The explicit Run command is the only command here that executes a
workflow.

Use **SCLPL: Restart Language Server** after changing environments or plugins, and
**SCLPL: Show Language Server Output** for startup diagnostics. The setup works on
Windows, Linux, macOS, virtual environments, devcontainers, and multi-root folders;
each workspace root receives separate local metadata lookup.

For contributors, run `npm run lint`, `npm run compile`, `npm test`, and `npm run
package` in `vscode`. Python language-service tests live in `language-server/tests`.
