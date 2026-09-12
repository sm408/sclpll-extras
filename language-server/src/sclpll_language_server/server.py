"""SCLPL's stdio language server.

The module intentionally imports pygls only when the server is launched.  Normal CLI
and runtime users therefore do not need Node, VS Code, or the optional editor extra.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote, urlparse

from sclpl import __version__
from sclpll_language_server.analysis import (
    DocumentAnalysis,
    SourceRange,
    analyze,
    callable_metadata,
    completions,
    format_sclpll,
    vocabulary,
)

LOG = logging.getLogger("sclpll.language")


def uri_to_path(uri: str) -> Path | None:
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    return Path(unquote(parsed.path.lstrip("/") if sys.platform == "win32" else parsed.path))


class AnalysisStore:
    """Small URI/version cache shared by all transport handlers."""

    def __init__(self) -> None:
        self._items: dict[str, DocumentAnalysis] = {}
        self.workspace_roots: tuple[Path, ...] = ()

    def workspace_for(self, uri: str) -> Path | None:
        path = uri_to_path(uri)
        if path is None:
            return None
        candidates = [root for root in self.workspace_roots if path.is_relative_to(root)]
        return max(candidates, key=lambda root: len(str(root)), default=None)

    def analyze(self, uri: str, source: str, version: int | None) -> DocumentAnalysis:
        cached = self._items.get(uri)
        if cached is not None and cached.version == version and cached.source == source:
            return cached
        result = analyze(source, uri=uri, version=version, workspace=self.workspace_for(uri))
        self._items[uri] = result
        return result

    def get(self, uri: str) -> DocumentAnalysis | None:
        return self._items.get(uri)

    def remove(self, uri: str) -> None:
        self._items.pop(uri, None)


def _span(types: Any, value: SourceRange) -> Any:
    return types.Range(
        start=types.Position(line=value.start_line, character=value.start_character),
        end=types.Position(line=value.end_line, character=value.end_character),
    )


def _document_symbol_kind(types: Any, kind: str) -> Any:
    names = {
        "workflow": "Namespace",
        "step": "Function",
        "var": "Variable",
        "rule": "Boolean",
        "mode": "Enum",
        "port": "Property",
    }
    return getattr(types.SymbolKind, names.get(kind, "String"))


def create_server() -> Any:
    """Build a pygls 2.x server, importing optional dependencies lazily."""
    try:
        from lsprotocol import types
        from pygls.lsp.server import LanguageServer
    except ModuleNotFoundError as error:  # clear CLI error, never a JSON-RPC stdout leak
        raise RuntimeError("SCLPLL language server requires: pip install sclpl pygls") from error

    server = LanguageServer("sclpl-language-server", __version__)
    store = AnalysisStore()
    settings = {"diagnostics": True, "semantic_highlighting": True}

    def current(uri: str) -> DocumentAnalysis | None:
        document = server.workspace.get_text_document(uri)
        return store.analyze(uri, document.source, document.version)

    def definition_for(result: DocumentAnalysis, name: str) -> Any | None:
        """Return a definition only when the source index makes it unambiguous."""
        definitions = [
            symbol
            for symbol in result.symbols
            if symbol.name == name and symbol.kind in {"step", "var", "rule", "mode", "port"}
        ]
        return definitions[0] if len(definitions) == 1 else None

    def publish(uri: str) -> None:
        if not settings["diagnostics"]:
            server.text_document_publish_diagnostics(
                types.PublishDiagnosticsParams(uri=uri, diagnostics=[])
            )
            return
        result = current(uri)
        if result is None:
            return
        diagnostics = [
            types.Diagnostic(
                range=_span(types, item.range),
                message=item.message,
                severity={
                    "error": types.DiagnosticSeverity.Error,
                    "warning": types.DiagnosticSeverity.Warning,
                    "information": types.DiagnosticSeverity.Information,
                    "hint": types.DiagnosticSeverity.Hint,
                }[item.severity],
                code=item.code,
                source="sclpl",
            )
            for item in result.diagnostics
        ]
        server.text_document_publish_diagnostics(
            types.PublishDiagnosticsParams(uri=uri, diagnostics=diagnostics)
        )

    @server.feature(types.INITIALIZE)
    def initialize(params: Any) -> None:
        options = getattr(params, "initialization_options", None) or {}
        if isinstance(options, dict):
            settings["diagnostics"] = bool(options.get("diagnostics", True))
            settings["semantic_highlighting"] = bool(options.get("semanticHighlighting", True))
        folders = list(params.workspace_folders or [])
        root_uri = getattr(params, "root_uri", None)
        roots = [uri_to_path(item.uri) for item in folders]
        if root_uri:
            roots.append(uri_to_path(root_uri))
        store.workspace_roots = tuple(item for item in roots if item is not None)
        LOG.info(
            "SCLPL language server %s started for %d workspace roots",
            __version__,
            len(store.workspace_roots),
        )

    @server.feature(types.TEXT_DOCUMENT_DID_OPEN)
    def did_open(params: Any) -> None:
        publish(params.text_document.uri)

    @server.feature(types.TEXT_DOCUMENT_DID_CHANGE)
    def did_change(params: Any) -> None:
        publish(params.text_document.uri)

    @server.feature(types.TEXT_DOCUMENT_DID_CLOSE)
    def did_close(params: Any) -> None:
        uri = params.text_document.uri
        store.remove(uri)
        server.text_document_publish_diagnostics(
            types.PublishDiagnosticsParams(uri=uri, diagnostics=[])
        )

    @server.feature(
        types.TEXT_DOCUMENT_COMPLETION,
        types.CompletionOptions(trigger_characters=["@", ":", " ", "="]),
    )
    def completion(params: Any) -> Any:
        uri = params.text_document.uri
        result = current(uri)
        if result is None:
            return types.CompletionList(is_incomplete=False, items=[])
        root = store.workspace_for(uri)
        items = []
        for item in completions(result, params.position.line, params.position.character, root):
            completion_kind = {
                "function": types.CompletionItemKind.Function,
                "keyword": types.CompletionItemKind.Keyword,
                "directive": types.CompletionItemKind.Keyword,
                "format": types.CompletionItemKind.TypeParameter,
                "reference": types.CompletionItemKind.Variable,
                "parameter": types.CompletionItemKind.Variable,
                "step": types.CompletionItemKind.Function,
                "port": types.CompletionItemKind.Property,
            }
            kind = completion_kind.get(str(item["kind"]), types.CompletionItemKind.Text)
            detail = cast(str | None, item.get("detail"))
            documentation = cast(str | None, item.get("documentation"))
            items.append(
                types.CompletionItem(
                    label=str(item["label"]),
                    kind=kind,
                    detail=detail,
                    documentation=documentation,
                )
            )
        return types.CompletionList(is_incomplete=False, items=items)

    @server.feature(types.TEXT_DOCUMENT_HOVER)
    def hover(params: Any) -> Any:
        result = current(params.text_document.uri)
        if result is None:
            return None
        hit = result.symbol_at(params.position.line, params.position.character)
        if hit is None:
            ref = result.reference_at(params.position.line, params.position.character)
            hit = next(
                (
                    symbol
                    for symbol in result.symbols
                    if ref is not None and symbol.name == ref.name
                ),
                None,
            )
        if hit is None:
            lexical = _lexical_hover(result, params.position.line, params.position.character)
            if lexical is None:
                return None
            title, detail, span = lexical
            return types.Hover(
                contents=types.MarkupContent(
                    kind=types.MarkupKind.Markdown,
                    value=f"**{title}**\n\n{detail}",
                ),
                range=_span(types, span),
            )
        body = f"**{hit.kind.title()}**: `{hit.name}`"
        if hit.kind == "callable":
            meta = callable_metadata(store.workspace_for(params.text_document.uri)).get(hit.name)
            if meta:
                body = f"`{meta[0]}`\n\n{meta[1]}"
        elif hit.detail:
            body += f"\n\n{hit.detail.title()} declaration"
        return types.Hover(
            contents=types.MarkupContent(kind=types.MarkupKind.Markdown, value=body),
            range=_span(types, hit.selection_range),
        )

    @server.feature(
        types.TEXT_DOCUMENT_SIGNATURE_HELP,
        types.SignatureHelpOptions(trigger_characters=["(", ",", "="]),
    )
    def signature_help(params: Any) -> Any:
        result = current(params.text_document.uri)
        if result is None:
            return None
        line = (
            result.source.splitlines()[params.position.line]
            if params.position.line < len(result.source.splitlines())
            else ""
        )
        before = line[: params.position.character].strip().split()
        name = before[0] if before else ""
        meta = callable_metadata(store.workspace_for(params.text_document.uri)).get(name)
        if meta is None:
            return None
        return types.SignatureHelp(
            signatures=[
                types.SignatureInformation(
                    label=meta[0],
                    documentation=meta[1],
                    parameters=[
                        types.ParameterInformation(label=parameter) for parameter in meta[2]
                    ],
                )
            ],
            active_signature=0,
            active_parameter=max(0, line[: params.position.character].count(",")),
        )

    @server.feature(types.TEXT_DOCUMENT_DEFINITION)
    def definition(params: Any) -> Any:
        result = current(params.text_document.uri)
        if result is None:
            return None
        ref = result.reference_at(params.position.line, params.position.character)
        hit = result.symbol_at(params.position.line, params.position.character)
        name = ref.name if ref else (hit.name if hit else "")
        definition = definition_for(result, name)
        resolved = (
            types.Location(
                uri=params.text_document.uri, range=_span(types, definition.selection_range)
            )
            if definition
            else None
        )
        if resolved is not None:
            return resolved
        script = _python_script_location(
            result,
            params.position.line,
            params.position.character,
            store.workspace_for(params.text_document.uri),
        )
        return (
            types.Location(
                uri=script.as_uri(),
                range=types.Range(
                    start=types.Position(line=0, character=0),
                    end=types.Position(line=0, character=0),
                ),
            )
            if script is not None
            else None
        )

    @server.feature(types.TEXT_DOCUMENT_REFERENCES)
    def references(params: Any) -> Any:
        result = current(params.text_document.uri)
        if result is None:
            return []
        hit = result.symbol_at(params.position.line, params.position.character)
        ref = result.reference_at(params.position.line, params.position.character)
        name = hit.name if hit else (ref.name if ref else "")
        definition = definition_for(result, name)
        if definition is None:
            return []
        related_kinds = {
            "step": {"step", "dependency"},
            "port": {"port", "write"},
        }.get(definition.kind, {definition.kind})
        spans = [
            symbol.selection_range
            for symbol in result.symbols
            if symbol.name == name and symbol.kind in related_kinds
        ]
        spans.extend(reference.range for reference in result.references if reference.name == name)
        return [
            types.Location(uri=params.text_document.uri, range=_span(types, item)) for item in spans
        ]

    @server.feature(types.TEXT_DOCUMENT_RENAME)
    def rename(params: Any) -> Any:
        result = current(params.text_document.uri)
        if (
            result is None
            or not params.new_name.replace("_", "a").replace("-", "a").isalnum()
            or params.new_name[0].isdigit()
        ):
            return None
        hit = result.symbol_at(params.position.line, params.position.character)
        ref = result.reference_at(params.position.line, params.position.character)
        name = hit.name if hit else (ref.name if ref else "")
        definition = definition_for(result, name)
        if definition is None:
            return None
        related_kinds = {
            "step": {"step", "dependency"},
            "port": {"port", "write"},
        }.get(definition.kind, {definition.kind})
        edits = [
            types.TextEdit(range=_span(types, item.selection_range), new_text=params.new_name)
            for item in result.symbols
            if item.name == name and item.kind in related_kinds
        ]
        edits.extend(
            types.TextEdit(range=_span(types, item.range), new_text="@" + params.new_name)
            for item in result.references
            if item.name == name
        )
        return types.WorkspaceEdit(changes={params.text_document.uri: edits})

    @server.feature(types.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
    def document_symbols(params: Any) -> Any:
        result = current(params.text_document.uri)
        if result is None:
            return []
        return [
            types.SymbolInformation(
                name=item.name,
                kind=_document_symbol_kind(types, item.kind),
                location=types.Location(
                    uri=params.text_document.uri, range=_span(types, item.range)
                ),
                container_name=item.kind.title(),
            )
            for item in result.symbols
            if item.kind in {"workflow", "step", "var", "rule", "mode", "port"}
        ]

    @server.feature(types.WORKSPACE_SYMBOL)
    def workspace_symbols(params: Any) -> Any:
        query = (params.query or "").lower()
        found = []
        for root in store.workspace_roots:
            for path in root.rglob("*.sclpll"):
                if any(part in {".git", ".venv", "node_modules"} for part in path.parts):
                    continue
                try:
                    result = store.analyze(path.as_uri(), path.read_text(encoding="utf-8"), None)
                except OSError:
                    continue
                for item in result.symbols:
                    if item.kind not in {"workflow", "step"} or query not in item.name.lower():
                        continue
                    found.append(
                        types.SymbolInformation(
                            name=item.name,
                            kind=_document_symbol_kind(types, item.kind),
                            location=types.Location(
                                uri=path.as_uri(), range=_span(types, item.range)
                            ),
                            container_name=item.kind.title(),
                        )
                    )
        return found[:200]

    semantic_legend = types.SemanticTokensLegend(
        token_types=["function", "variable", "property", "namespace", "keyword", "type"],
        token_modifiers=["declaration", "definition", "defaultLibrary"],
    )

    @server.feature(
        types.TEXT_DOCUMENT_SEMANTIC_TOKENS_FULL,
        semantic_legend,
    )
    def semantic_tokens(params: Any) -> Any:
        if not settings["semantic_highlighting"]:
            return types.SemanticTokens(data=[])
        result = current(params.text_document.uri)
        if result is None:
            return types.SemanticTokens(data=[])
        token_type = {
            "callable": 0,
            "var": 1,
            "step": 2,
            "port": 2,
            "workflow": 3,
            "rule": 1,
            "mode": 1,
        }
        items: list[tuple[SourceRange, int, int]] = [
            (
                item.selection_range,
                token_type[item.kind],
                1 if item.kind in {"step", "var", "rule", "port", "workflow", "mode"} else 4,
            )
            for item in result.symbols
            if item.kind in token_type
        ]
        definitions = {
            item.name: item.kind
            for item in result.symbols
            if item.kind in {"step", "var", "rule", "port", "mode"}
        }
        for reference in result.references:
            reference_kind = definitions.get(reference.name)
            if reference_kind in token_type:
                items.append((reference.range, token_type[reference_kind], 0))
        items.sort(key=lambda item: (item[0].start_line, item[0].start_character))
        data: list[int] = []
        previous_line = previous_character = 0
        for span, semantic_kind, modifiers in items:
            delta_line = span.start_line - previous_line
            delta_character = span.start_character - (previous_character if delta_line == 0 else 0)
            data.extend(
                [
                    delta_line,
                    delta_character,
                    span.end_character - span.start_character,
                    semantic_kind,
                    modifiers,
                ]
            )
            previous_line, previous_character = span.start_line, span.start_character
        return types.SemanticTokens(data=data)

    @server.feature(types.TEXT_DOCUMENT_FORMATTING)
    def formatting(params: Any) -> Any:
        document = server.workspace.get_text_document(params.text_document.uri)
        try:
            rendered = format_sclpll(document.source, origin=params.text_document.uri)
        except Exception:
            return []
        lines = document.source.splitlines()
        return [
            types.TextEdit(
                range=types.Range(
                    start=types.Position(line=0, character=0),
                    end=types.Position(line=len(lines), character=0),
                ),
                new_text=rendered,
            )
        ]

    @server.feature(types.TEXT_DOCUMENT_FOLDING_RANGE)
    def folding(params: Any) -> Any:
        result = current(params.text_document.uri)
        if result is None:
            return []
        out = []
        stack: list[tuple[int, int]] = []
        for token in result.tokens:
            if token.kind.name == "INDENT":
                stack.append((token.line - 2, token.column))
            elif token.kind.name == "DEDENT" and stack:
                start, _ = stack.pop()
                if token.line - 2 > start:
                    out.append(types.FoldingRange(start_line=start, end_line=token.line - 2))
        return out

    @server.feature(types.TEXT_DOCUMENT_CODE_ACTION)
    def code_actions(params: Any) -> Any:
        result = current(params.text_document.uri)
        if result is None:
            return []
        actions = [
            types.CodeAction(
                title="Format document",
                kind=types.CodeActionKind.Source,
                command=types.Command(title="Format document", command="sclpl.format"),
            )
        ]
        requested = _from_lsp_range(params.range)
        for diagnostic in result.diagnostics:
            if not _ranges_overlap(diagnostic.range, requested):
                continue
            for remedy in diagnostic.remedies:
                if remedy.startswith("did you mean ") and "'" in remedy:
                    suggestion = remedy.split("'", 2)[1]
                    replacement = "@" + suggestion if diagnostic.code == "SCLPL100" else suggestion
                    actions.append(
                        types.CodeAction(
                            title=f"Change to {suggestion}",
                            kind=types.CodeActionKind.QuickFix,
                            edit=types.WorkspaceEdit(
                                changes={
                                    params.text_document.uri: [
                                        types.TextEdit(
                                            range=_span(types, diagnostic.range),
                                            new_text=replacement,
                                        )
                                    ]
                                }
                            ),
                        )
                    )
        return actions

    @server.feature(types.TEXT_DOCUMENT_CODE_LENS)
    def code_lens(params: Any) -> Any:
        result = current(params.text_document.uri)
        if result is None:
            return []
        workflow = next((item for item in result.symbols if item.kind == "workflow"), None)
        if workflow is None:
            return []
        return [
            types.CodeLens(
                range=_span(types, workflow.range),
                command=types.Command(
                    title=title, command=command, arguments=[params.text_document.uri]
                ),
            )
            for title, command in (
                ("Run Workflow", "sclpl.run"),
                ("Validate", "sclpl.validate"),
                ("Explain", "sclpl.explain"),
                ("Graph", "sclpl.graph"),
            )
        ]

    return server


def _from_lsp_range(value: Any) -> SourceRange:
    return SourceRange(value.start.line, value.start.character, value.end.line, value.end.character)


def _ranges_overlap(first: SourceRange, second: SourceRange) -> bool:
    """Whether two editor ranges overlap (including a caret inside a diagnostic)."""
    if first.end_line < second.start_line or second.end_line < first.start_line:
        return False
    if first.start_line != first.end_line or second.start_line != second.end_line:
        return True
    return (
        first.start_character <= second.end_character
        and second.start_character <= first.end_character
    )


def _lexical_hover(
    analysis: DocumentAnalysis, line: int, character: int
) -> tuple[str, str, SourceRange] | None:
    """Describe canonical lexical vocabulary when no semantic symbol owns it."""
    lines = analysis.source.splitlines()
    if line < 0 or line >= len(lines):
        return None
    raw = lines[line]
    for match in re.finditer(r"@[A-Za-z_][A-Za-z0-9_-]*|[A-Za-z_][A-Za-z0-9_-]*", raw):
        if not match.start() <= character <= match.end():
            continue
        text = match.group()
        word = text[1:] if text.startswith("@") else text
        vocab = vocabulary()
        category = (
            ("Directive", "A top-level SCLPLL declaration.", word in vocab["directives"])
            if text.startswith("@")
            else ("HTTP method", "A request step method.", word in vocab["methods"])
        )
        categories = (
            category,
            ("Control", "A structural step kind.", word in vocab["controls"]),
            (
                "Request clause",
                "A clause accepted by request steps.",
                word in vocab["request_clauses"],
            ),
            ("Common clause", "A common step execution clause.", word in vocab["common_clauses"]),
            ("Mode clause", "A declaration inside a mode block.", word in vocab["mode_clauses"]),
            ("Format", "A canonical SCLPL table format.", word in vocab["formats"]),
        )
        for title, detail, matches in categories:
            if matches:
                return (
                    title,
                    f"`{word}` — {detail}",
                    _range_for_word(line, match.start(), match.end()),
                )
    return None


def _range_for_word(line: int, start: int, end: int) -> SourceRange:
    return SourceRange(line, start, line, end)


def _python_script_location(
    analysis: DocumentAnalysis, line: int, character: int, workspace: Path | None
) -> Path | None:
    """Resolve only a quoted local ``python`` step path under its workspace."""
    if workspace is None or line < 0 or line >= len(analysis.source.splitlines()):
        return None
    raw = analysis.source.splitlines()[line]
    match = re.match(r"\s*python\s+(['\"])([^'\"]+)\1", raw)
    if match is None or not match.start(2) <= character <= match.end(2):
        return None
    candidate = (workspace / match.group(2)).resolve()
    try:
        candidate.relative_to(workspace.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SCLPL language server")
    parser.add_argument("--stdio", action="store_true", help="run over standard input/output")
    parser.parse_args(argv)
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(name)s: %(message)s")
    try:
        server = create_server()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 2
    server.start_io()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
