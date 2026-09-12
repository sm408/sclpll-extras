"""Passive, editor-neutral analysis for SCLPLL.

This deliberately does not contain a parser.  It uses ``run.sclpll.parse`` for
validity, while retaining lexical structure only to attach useful source spans and
to provide safe features while a document is incomplete.
"""

from __future__ import annotations

from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from sclpl.errors import SclplError, did_you_mean
from sclpl.ext import functions, plugins
from sclpl.run.ir import FnConfig, WorkflowDoc
from sclpl.run.preflight import preflight
from sclpl.run.sclpll import emit, parse
from sclpl.run.sclpll.lex import Kind, Token, tokenize
from sclpl.run.sclpll.parse import CONTROL_VERBS, DIRECTIVES, METHODS, REQUEST_VERBS
from sclpl.tables.io import FORMATS

Severity = Literal["error", "warning", "information", "hint"]


@dataclass(frozen=True, slots=True)
class SourceRange:
    start_line: int
    start_character: int
    end_line: int
    end_character: int


@dataclass(frozen=True, slots=True)
class EditorDiagnostic:
    message: str
    severity: Severity
    range: SourceRange
    code: str | None = None
    remedies: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Symbol:
    name: str
    kind: str
    range: SourceRange
    selection_range: SourceRange
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Reference:
    name: str
    kind: str
    range: SourceRange


@dataclass(slots=True)
class DocumentAnalysis:
    uri: str
    version: int | None
    source: str
    tokens: list[Token]
    doc: WorkflowDoc | None
    symbols: list[Symbol] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)
    diagnostics: list[EditorDiagnostic] = field(default_factory=list)

    def symbol_at(self, line: int, character: int) -> Symbol | None:
        return next(
            (item for item in self.symbols if _contains(item.selection_range, line, character)),
            None,
        )

    def reference_at(self, line: int, character: int) -> Reference | None:
        return next(
            (item for item in self.references if _contains(item.range, line, character)), None
        )


def format_sclpll(source: str, *, origin: str = "<editor>") -> str:
    """Format through the canonical parser/emitter; never format invalid source."""
    return emit(parse(source, origin=origin))


def vocabulary() -> dict[str, tuple[str, ...]]:
    """Canonical vocabulary exposed for clients without duplicating DSL constants."""
    return {
        "directives": tuple(sorted(DIRECTIVES)),
        "methods": tuple(METHODS),
        "request_clauses": tuple(sorted(REQUEST_VERBS)),
        "common_clauses": tuple(sorted(CONTROL_VERBS)),
        "formats": tuple(sorted(FORMATS)),
        "controls": ("let", "foreach", "when", "while", "do_while", "parallel", "gate"),
        "mode_clauses": (
            "include",
            "exclude",
            "extends",
            "describe",
            "var",
            "limit",
            "stub",
            "all",
        ),
    }


def callable_metadata(
    workspace: Path | None = None,
) -> dict[str, tuple[str, str, tuple[str, ...], bool]]:
    """Return callable name -> (signature, summary, parameters, builtin).

    Built-ins are already registered by SCLPL bootstrap.  Plugin manifests are read
    without activation, so merely editing a file cannot execute plugin code.
    """
    try:
        from sclpl import bootstrap

        bootstrap.load(plugins=False)
    except Exception:  # pragma: no cover - a broken optional integration stays passive
        pass
    values = {
        name: (
            entry.signature(),
            entry.summary,
            tuple(p.name for p in entry.parameters),
            entry.builtin,
        )
        for name, entry in functions.REGISTRY.items()
    }
    try:
        registry = plugins.discover(
            activate=False, extra_dirs=(() if workspace is None else (workspace / "plugins",))
        )
        for plugin in registry.plugins.values():
            for contribution in plugin.contributes:
                if contribution.kind in {"function", "connector", "verb"} and contribution.name:
                    values.setdefault(
                        contribution.name,
                        (
                            contribution.signature or f"{contribution.name}(...)",
                            contribution.summary or plugin.description,
                            contribution.parameters,
                            False,
                        ),
                    )
    except Exception:
        # Discovery itself is intentionally best effort: a malformed optional plugin
        # must not remove core editing support.
        pass
    return values


def plugin_problems(workspace: Path | None = None) -> tuple[str, ...]:
    """Return redaction-safe passive plugin discovery failures.

    Discovery reads manifests only (``activate=False``), so reporting an invalid
    plugin while a document is open neither imports plugin code nor exposes
    configuration values.  Keep one message per plugin: editor diagnostics must
    explain why vocabulary is absent without turning one broken optional plugin
    into a wall of squiggles.
    """
    try:
        registry = plugins.discover(
            activate=False, extra_dirs=(() if workspace is None else (workspace / "plugins",))
        )
    except Exception:
        return ("plugin metadata could not be read",)
    return tuple(
        f"plugin {plugin.name!r}: {plugin.refused}"
        for plugin in registry.plugins.values()
        if plugin.refused
    )


def project_values(workspace: Path | None) -> dict[str, tuple[str, ...]]:
    """Read only non-secret project names useful while editing.

    The project loader validates the same manifest shape the CLI uses. We intentionally
    expose profile *names* only: credentials, endpoints, and plugin setting values are
    never copied into editor results or logs.
    """
    if workspace is None:
        return {"auth": (), "modes": (), "plugins": ()}
    try:
        from sclpl.project.context import load

        context = load(workspace)
    except Exception:
        return {"auth": (), "modes": (), "plugins": ()}
    if context is None:
        return {"auth": (), "modes": (), "plugins": ()}
    auth = context.manifest.get("auth", {})
    plugin_names = context.plugin_settings
    return {
        "auth": tuple(sorted(name for name in auth if isinstance(name, str))),
        "modes": tuple(
            sorted(
                name for name in context.manifest.get("environments", {}) if isinstance(name, str)
            )
        ),
        "plugins": tuple(sorted(plugin_names)),
    }


def analyze(
    source: str, *, uri: str = "<editor>", version: int | None = None, workspace: Path | None = None
) -> DocumentAnalysis:
    """Analyze source using only static/local operations.

    Lexer diagnostics are retained even when parsing cannot continue.  On success we
    add IR-level checks and build a semantic source index; no workflow function,
    connector, script, network request, or resource provider is invoked.
    """
    result = DocumentAnalysis(uri=uri, version=version, source=source, tokens=[], doc=None)
    try:
        result.tokens = tokenize(source, origin=uri)
    except SclplError as error:
        result.diagnostics.append(_error_diagnostic(error, source, "SCLPL001"))
        result.symbols, result.references = _source_index(source, [])
        return result

    result.symbols, result.references = _source_index(source, result.tokens)
    try:
        result.doc = parse(source, origin=uri)
    except (SclplError, ValueError) as error:
        lexical = _safe_lexical_diagnostics(source, result.tokens)
        primary = _error_diagnostic(error, source, "SCLPL100")
        # Known lexical mistakes have a narrower span than the parser's otherwise
        # deliberate line-level recovery diagnostic.
        if not (
            lexical and primary.message.startswith(("unknown directive", "1 validation error"))
        ):
            result.diagnostics.append(primary)
        result.diagnostics.extend(lexical)
        result.diagnostics.extend(_duplicate_diagnostics(result.symbols))
        return result

    result.diagnostics.extend(_semantic_diagnostics(result, workspace))
    result.diagnostics.extend(_preflight_diagnostics(result))
    return result


def completions(
    analysis: DocumentAnalysis, line: int, character: int, workspace: Path | None = None
) -> list[dict[str, object]]:
    """Context-sensitive candidates represented in an LSP-neutral shape."""
    prefix = _line_prefix(analysis.source, line, character)
    values: list[dict[str, object]] = []
    vocab = vocabulary()
    stripped = prefix.lstrip()
    if not prefix[: len(prefix) - len(stripped)]:
        values.extend(_items((f"@{item}" for item in vocab["directives"]), "directive"))
    elif _port_context(prefix):
        values.extend(_items(vocab["formats"], "format"))
    elif stripped.startswith("@step") and "<-" in prefix and "->" not in prefix:
        values.extend(_items((s.name for s in analysis.symbols if s.kind == "step"), "step"))
    elif stripped.startswith("@step") and "->" in prefix:
        values.extend(
            _items(
                (s.name for s in analysis.symbols if s.kind == "port" and s.detail == "output"),
                "port",
            )
        )
    elif "@" in prefix and not stripped.startswith("@"):
        values.extend(_items(_reference_candidates(analysis, line), "reference"))
    elif stripped.startswith("auth "):
        values.extend(_items(project_values(workspace)["auth"], "reference"))
    elif stripped.startswith("@default_mode "):
        values.extend(_items((s.name for s in analysis.symbols if s.kind == "mode"), "reference"))
    elif _in_mode(analysis.tokens, line):
        values.extend(_items(vocab["mode_clauses"], "keyword"))
    elif _in_step(analysis.tokens, line):
        token = _token_on_line(analysis.tokens, line)
        callables = callable_metadata(workspace)
        if token is not None and token.line - 1 == line:
            values.extend(_items((*vocab["methods"], *vocab["controls"]), "keyword"))
            values.extend(_callable_items(callables))
            if token.head in callables:
                signature, summary, parameters, _ = callables[token.head]
                values.extend(
                    {
                        "label": f"{parameter}=",
                        "kind": "parameter",
                        "detail": signature,
                        "documentation": summary,
                    }
                    for parameter in parameters
                )
        values.extend(_items((*vocab["request_clauses"], *vocab["common_clauses"]), "keyword"))
    else:
        values.extend(_items((f"@{item}" for item in vocab["directives"]), "directive"))
    # Stable, context-first de-duplication.
    seen: set[str] = set()
    unique: list[dict[str, object]] = []
    for item in values:
        label = str(item["label"])
        if label not in seen:
            seen.add(label)
            unique.append(item)
    return unique[:200]


def _semantic_diagnostics(
    analysis: DocumentAnalysis, workspace: Path | None
) -> list[EditorDiagnostic]:
    assert analysis.doc is not None
    doc = analysis.doc
    diagnostics: list[EditorDiagnostic] = []
    names = {step.id for step in doc.all_steps()}
    outputs = {port.name for port in doc.outputs}
    known_values = names | set(doc.vars) | set(doc.rules) | {port.name for port in doc.inputs}
    callable_names = callable_metadata(workspace)
    # Manifest discovery is safe and bounded.  Do it once per analysis so a
    # malformed optional plugin explains its missing vocabulary without
    # preventing core diagnostics from being produced.
    for problem in plugin_problems(workspace):
        diagnostics.append(
            EditorDiagnostic(
                message=problem,
                severity="warning",
                range=_range(0, 0, 1),
                code="SCLPL700",
            )
        )
    for symbol in analysis.symbols:
        if symbol.kind == "dependency" and symbol.name not in names:
            diagnostics.append(
                _diagnostic(f"unknown dependency {symbol.name!r}", symbol.range, "SCLPL400")
            )
        elif symbol.kind == "write" and symbol.name not in outputs:
            diagnostics.append(
                _diagnostic(f"unknown output port {symbol.name!r}", symbol.range, "SCLPL300")
            )
        elif symbol.kind == "format" and symbol.name not in FORMATS:
            diagnostics.append(
                _diagnostic(f"unknown format {symbol.name!r}", symbol.range, "SCLPL200")
            )
        elif symbol.kind == "callable" and symbol.name not in callable_names:
            suggestion = did_you_mean(symbol.name, callable_names)
            diagnostics.append(
                _diagnostic(
                    f"unknown function or connector {symbol.name!r}",
                    symbol.range,
                    "SCLPL500",
                    (suggestion,) if suggestion else (),
                )
            )
    for reference in analysis.references:
        local_names = _loop_bindings_at(
            analysis.source, analysis.tokens, reference.range.start_line
        )
        if reference.name not in known_values | local_names | {"result", "rows", "item"}:
            diagnostics.append(
                _diagnostic(f"unresolved reference @{reference.name}", reference.range, "SCLPL300")
            )
    diagnostics.extend(_function_argument_diagnostics(analysis))
    return diagnostics


def _function_argument_diagnostics(analysis: DocumentAnalysis) -> list[EditorDiagnostic]:
    """Check statically knowable argument-shape mistakes without calling a function."""
    assert analysis.doc is not None
    out: list[EditorDiagnostic] = []
    for step in analysis.doc.all_steps():
        config = step.config
        if not isinstance(config, FnConfig):
            continue
        entry = functions.REGISTRY.get(config.name)
        if entry is None:
            continue  # A manifest-only plugin has no safely inspectable signature.
        parameters = entry.parameters
        names = {item.name for item in parameters}
        variadic = any(item.variadic for item in parameters)
        positional = [item for item in parameters if not item.keyword_only and not item.variadic]
        span = _callable_range(analysis, config.name)
        if len(config.args) > len(positional) and not variadic:
            out.append(
                _diagnostic(
                    f"{config.name}() accepts at most {len(positional)} positional arguments",
                    span,
                    "SCLPL500",
                )
            )
        for key in config.kwargs:
            if key not in names and not variadic:
                suggestion = did_you_mean(key, names)
                out.append(
                    _diagnostic(
                        f"{config.name}() has no argument {key!r}",
                        _keyword_range(analysis, config.name, key),
                        "SCLPL500",
                        (suggestion,) if suggestion else (),
                    )
                )
        provided = set(config.kwargs) | {item.name for item in positional[: len(config.args)]}
        for parameter in parameters:
            if step.writes and parameter.name == "path":
                continue  # Canonical output binding supplies the destination path.
            if parameter.required and not parameter.variadic and parameter.name not in provided:
                out.append(
                    _diagnostic(
                        f"{config.name}() is missing required argument {parameter.name!r}",
                        span,
                        "SCLPL500",
                        (entry.signature(),),
                    )
                )
    return out


def _callable_range(analysis: DocumentAnalysis, name: str) -> SourceRange:
    return next(
        (
            item.selection_range
            for item in analysis.symbols
            if item.kind == "callable" and item.name == name
        ),
        _range(0, 0, 1),
    )


def _keyword_range(analysis: DocumentAnalysis, callable_name: str, key: str) -> SourceRange:
    for token in analysis.tokens:
        if token.kind is Kind.LINE and token.head == callable_name:
            offset = token.raw.find(f"{key}=")
            if offset >= 0:
                return _range(token.line - 1, offset, offset + len(key))
    return _callable_range(analysis, callable_name)


def _preflight_diagnostics(analysis: DocumentAnalysis) -> list[EditorDiagnostic]:
    """Surface graph/mode/function errors the canonical static validator can prove.

    ``preflight`` deliberately does no I/O when both port binding and file checks are
    disabled. It remains the source of truth for cycles and graph closure instead of
    reimplementing either rule for the editor.
    """
    assert analysis.doc is not None
    report = preflight(analysis.doc, check_files=False, require_ports=False)
    out: list[EditorDiagnostic] = []
    for problem in report.problems:
        message = problem.diagnostic.message
        code = (
            "SCLPL400"
            if any(word in message.lower() for word in ("cycle", "depend", "graph", "loop"))
            else "SCLPL300"
        )
        span = _best_problem_range(message, analysis.symbols)
        out.append(_diagnostic(message, span, code, tuple(problem.diagnostic.remedies)))
    return out


def _best_problem_range(message: str, symbols: list[Symbol]) -> SourceRange:
    """Attach canonical validation text to its most specific indexed identifier."""
    quoted = [piece for piece in message.split("'") if piece]
    for value in quoted:
        found = next((item for item in symbols if item.name == value), None)
        if found is not None:
            return found.selection_range
    return symbols[0].range if symbols else _range(0, 0, 1)


def _source_index(source: str, tokens: list[Token]) -> tuple[list[Symbol], list[Reference]]:
    symbols: list[Symbol] = []
    refs: list[Reference] = []
    lines = source.splitlines()
    step_body_lines: set[int] = set()
    for token in tokens:
        if token.kind is Kind.DIRECTIVE:
            line = token.line - 1
            name_range = _range(line, token.column, token.column + len(token.head) + 1)
            rest_offset = _rest_start(token)
            parts = token.rest.split()
            if token.head == "workflow" and parts:
                symbols.append(
                    Symbol(
                        parts[0].strip("'\""),
                        "workflow",
                        name_range,
                        _range(line, rest_offset, rest_offset + len(parts[0])),
                    )
                )
            elif token.head in {"var", "rule"} and parts:
                name = parts[0]
                symbols.append(
                    Symbol(
                        name,
                        token.head,
                        name_range,
                        _range(line, rest_offset, rest_offset + len(name)),
                    )
                )
            elif token.head in {"input", "output"} and parts:
                spec = parts[0].rstrip("?")
                port, _, fmt = spec.partition(":")
                pos = rest_offset
                symbols.append(
                    Symbol(
                        port,
                        "port",
                        _range(line, pos, pos + len(spec)),
                        _range(line, pos, pos + len(port)),
                        token.head,
                    )
                )
                if fmt:
                    fmt_at = pos + len(port) + 1
                    symbols.append(
                        Symbol(
                            fmt,
                            "format",
                            _range(line, fmt_at, fmt_at + len(fmt)),
                            _range(line, fmt_at, fmt_at + len(fmt)),
                        )
                    )
            elif token.head == "mode" and parts:
                symbols.append(
                    Symbol(
                        parts[0],
                        "mode",
                        name_range,
                        _range(line, rest_offset, rest_offset + len(parts[0])),
                    )
                )
            elif token.head == "step" and parts:
                step = parts[0]
                symbols.append(
                    Symbol(
                        step, "step", name_range, _range(line, rest_offset, rest_offset + len(step))
                    )
                )
                if "<-" in token.rest:
                    tail = token.rest.split("<-", 1)[1].split("->", 1)[0]
                    base = line_text_offset(lines[line], tail)
                    for dep in tail.split():
                        at = lines[line].find(dep, base)
                        symbols.append(
                            Symbol(
                                dep,
                                "dependency",
                                _range(line, at, at + len(dep)),
                                _range(line, at, at + len(dep)),
                            )
                        )
                        base = at + len(dep)
                if "->" in token.rest:
                    port = (
                        token.rest.split("->", 1)[1].strip().split()[0]
                        if token.rest.split("->", 1)[1].strip()
                        else ""
                    )
                    if port:
                        at = lines[line].rfind(port)
                        symbols.append(
                            Symbol(
                                port,
                                "write",
                                _range(line, at, at + len(port)),
                                _range(line, at, at + len(port)),
                            )
                        )
        elif token.kind is Kind.LINE:
            step_body_lines.add(token.line - 1)
            if token.head not in {
                *METHODS,
                *REQUEST_VERBS,
                *CONTROL_VERBS,
                "let",
                "foreach",
                "when",
                "while",
                "do_while",
                "parallel",
                "gate",
                "branch",
                "otherwise",
                "concurrency",
                "collect",
                "include",
                "exclude",
                "extends",
                "describe",
                "var",
                "limit",
                "stub",
            }:
                at = token.column
                symbols.append(
                    Symbol(
                        token.head,
                        "callable",
                        _range(token.line - 1, at, at + len(token.head)),
                        _range(token.line - 1, at, at + len(token.head)),
                    )
                )
    for line_number, raw in enumerate(lines):
        code = _without_strings_and_comments(raw)
        # A top-level directive starts with @ but is never a value reference.
        start = 1 if code.lstrip().startswith("@") and len(code) == len(code.lstrip()) else 0
        cursor = start
        while cursor < len(code):
            if (
                code[cursor] == "@"
                and cursor + 1 < len(code)
                and (code[cursor + 1].isalpha() or code[cursor + 1] == "_")
            ):
                end = cursor + 2
                while end < len(code) and (code[end].isalnum() or code[end] in "_-"):
                    end += 1
                name = code[cursor + 1 : end]
                if not (cursor == 0 and name in DIRECTIVES):
                    refs.append(Reference(name, "value", _range(line_number, cursor, end)))
                cursor = end
            else:
                cursor += 1
    return symbols, refs


def _safe_lexical_diagnostics(source: str, tokens: list[Token]) -> list[EditorDiagnostic]:
    diagnostics: list[EditorDiagnostic] = []
    for token in tokens:
        if token.kind is Kind.DIRECTIVE and token.head not in DIRECTIVES:
            suggestion = did_you_mean(token.head, DIRECTIVES)
            diagnostics.append(
                _diagnostic(
                    f"unknown directive @{token.head}",
                    _range(token.line - 1, token.column, token.column + len(token.head) + 1),
                    "SCLPL100",
                    (suggestion,) if suggestion else (),
                )
            )
        if token.kind is Kind.DIRECTIVE and token.head in {"input", "output"} and ":" in token.rest:
            value = token.rest.split(":", 1)[1].rstrip("?").split()[0]
            if value not in FORMATS:
                at = token.raw.find(value)
                suggestion = did_you_mean(value, FORMATS)
                diagnostics.append(
                    _diagnostic(
                        f"unknown format {value!r}",
                        _range(token.line - 1, at, at + len(value)),
                        "SCLPL200",
                        (suggestion,) if suggestion else (),
                    )
                )
    return diagnostics


def _duplicate_diagnostics(symbols: list[Symbol]) -> list[EditorDiagnostic]:
    """Recover the second declaration span when IR validation rejects duplicates."""
    out: list[EditorDiagnostic] = []
    for kind in ("step", "port", "var", "rule", "mode"):
        seen: set[str] = set()
        for symbol in (item for item in symbols if item.kind == kind):
            if symbol.name in seen:
                out.append(
                    _diagnostic(
                        f"duplicate {kind} {symbol.name!r}",
                        symbol.selection_range,
                        "SCLPL300",
                    )
                )
            seen.add(symbol.name)
    return out


def _error_diagnostic(error: Exception, source: str, code: str) -> EditorDiagnostic:
    message = getattr(getattr(error, "diagnostic", None), "message", str(error)).splitlines()[0]
    where = getattr(getattr(error, "diagnostic", None), "where", "") or ""
    line = 0
    with suppress(ValueError, IndexError):
        line = max(0, int(where.rsplit(":", 1)[1]) - 1)
    raw = source.splitlines()[line] if line < len(source.splitlines()) else ""
    remedies = tuple(getattr(getattr(error, "diagnostic", None), "remedies", ()))
    if "unterminated string" in message:
        quote_at = min((index for index in (raw.find("'"), raw.find('"')) if index >= 0), default=0)
        return _diagnostic(
            message, _range(line, quote_at, max(quote_at + 1, len(raw))), code, remedies
        )
    return _diagnostic(message, _range(line, 0, max(1, len(raw))), code, remedies)


def _diagnostic(
    message: str, span: SourceRange, code: str, remedies: tuple[str | None, ...] = ()
) -> EditorDiagnostic:
    return EditorDiagnostic(message, "error", span, code, tuple(item for item in remedies if item))


def _range(line: int, start: int, end: int) -> SourceRange:
    return SourceRange(line, max(0, start), line, max(start + 1, end))


def _contains(span: SourceRange, line: int, character: int) -> bool:
    return (
        span.start_line == line == span.end_line
        and span.start_character <= character <= span.end_character
    )


def _rest_start(token: Token) -> int:
    return (
        token.raw.find(token.rest, token.column + len(token.head) + 1)
        if token.rest
        else token.column + len(token.head) + 1
    )


def _without_strings_and_comments(raw: str) -> str:
    out: list[str] = []
    quote: str | None = None
    escaped = False
    for char in raw:
        if quote:
            out.append(" ")
            if char == quote and not escaped:
                quote = None
            escaped = char == "\\" and not escaped
        elif char in "'\"":
            quote = char
            out.append(" ")
        elif char == "#":
            out.extend(" " * (len(raw) - len(out)))
            break
        else:
            out.append(char)
    return "".join(out)


def line_text_offset(raw: str, fragment: str) -> int:
    return raw.find(fragment)


def _line_prefix(source: str, line: int, character: int) -> str:
    lines = source.splitlines()
    return lines[line][:character] if 0 <= line < len(lines) else ""


def _port_context(prefix: str) -> bool:
    return prefix.lstrip().startswith(("@input ", "@output ")) and ":" in prefix


def _in_step(tokens: list[Token], line: int) -> bool:
    preceding = [
        token for token in tokens if token.kind is Kind.DIRECTIVE and token.line - 1 < line
    ]
    return bool(preceding and preceding[-1].head == "step")


def _in_mode(tokens: list[Token], line: int) -> bool:
    preceding = [
        token for token in tokens if token.kind is Kind.DIRECTIVE and token.line - 1 < line
    ]
    return bool(preceding and preceding[-1].head == "mode")


def _token_on_line(tokens: list[Token], line: int) -> Token | None:
    return next(
        (token for token in tokens if token.line - 1 == line and token.kind is Kind.LINE), None
    )


def _reference_candidates(analysis: DocumentAnalysis, line: int) -> tuple[str, ...]:
    return tuple(
        symbol.name
        for symbol in analysis.symbols
        if symbol.kind in {"step", "var", "rule", "port", "mode"}
    ) + tuple(sorted(_loop_bindings_at(analysis.source, analysis.tokens, line)))


def _loop_bindings_at(source: str, tokens: list[Token], line: int) -> set[str]:
    """Return lexical ``foreach`` bindings visible at a zero-based source line."""
    lines = source.splitlines()
    visible: set[str] = set()
    for token in tokens:
        token_line = token.line - 1
        if token.kind is not Kind.LINE or token.head != "foreach" or token_line >= line:
            continue
        binding = _foreach_binding(token.rest)
        if binding is None:
            continue
        indent = len(lines[token_line]) - len(lines[token_line].lstrip(" \t"))
        if line < len(lines):
            current_indent = len(lines[line]) - len(lines[line].lstrip(" \t"))
            if current_indent <= indent:
                continue
        visible.add(binding)
    return visible


def _foreach_binding(rest: str) -> str | None:
    parts = rest.split()
    if not parts:
        return None
    if len(parts) >= 3 and parts[1] == "in":
        return parts[0]
    if len(parts) >= 3 and parts[1] == "as":
        return parts[2]
    if len(parts) >= 2 and parts[0].startswith("@"):
        return parts[1]
    return "item" if parts[0].startswith("@") else None


def _items(labels: Iterable[str], kind: str) -> list[dict[str, object]]:
    return [{"label": label, "kind": kind} for label in labels]


def _callable_items(
    values: dict[str, tuple[str, str, tuple[str, ...], bool]],
) -> list[dict[str, object]]:
    return [
        {"label": name, "kind": "function", "detail": value[0], "documentation": value[1]}
        for name, value in sorted(values.items())
    ]
