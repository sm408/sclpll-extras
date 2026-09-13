from __future__ import annotations

from pathlib import Path

from sclpl.language.analysis import (
    analyze,
    callable_metadata,
    completions,
    format_sclpll,
    vocabulary,
)

VALID = """@workflow orders "Demo"
@var base = "https://example.test"
@input source:json
@output report:json
@rule healthy = @fetch.status == 200
@mode smoke
  include fetch
@step fetch
  get {{base}}/orders
@step transform <- fetch -> report
  save_json @fetch
"""


def test_analysis_uses_parser_and_indexes_symbols_and_references() -> None:
    result = analyze(VALID, uri="file:///orders.sclpll", version=7)

    assert result.doc is not None
    assert not result.diagnostics
    assert {(item.kind, item.name) for item in result.symbols} >= {
        ("workflow", "orders"),
        ("var", "base"),
        ("step", "fetch"),
        ("step", "transform"),
        ("dependency", "fetch"),
        ("write", "report"),
    }
    assert any(item.name == "fetch" for item in result.references)


def test_bad_format_and_unknown_dependency_have_precise_spans() -> None:
    source = "@workflow demo\n@input data:jsno\n@step process <- absent\n  save_json @absent\n"
    result = analyze(source)

    format_issue = next(item for item in result.diagnostics if item.code == "SCLPL200")
    assert (format_issue.range.start_line, format_issue.range.start_character) == (1, 12)

    # The parser stops at the bad port, while the editor deliberately keeps only
    # the more precise independent token diagnostic instead of duplicating it.
    assert not any(item.code == "SCLPL100" for item in result.diagnostics)


def test_static_unknown_callable_and_reference_are_reported_without_execution() -> None:
    result = analyze("@workflow demo\n@step fetch\n  fetxh @missing\n")

    assert {(item.code, item.message) for item in result.diagnostics} >= {
        ("SCLPL500", "unknown function or connector 'fetxh'"),
        ("SCLPL300", "unresolved reference @missing"),
    }
    callable_issue = next(item for item in result.diagnostics if item.code == "SCLPL500")
    assert callable_issue.range.start_character == 2


def test_contextual_completion_and_canonical_formatting() -> None:
    result = analyze(VALID)
    labels = {str(item["label"]) for item in completions(result, 8, 2)}

    assert {"get", "sleep", "python"} <= labels
    assert "json" in vocabulary()["formats"]
    assert format_sclpll(VALID).startswith('@workflow orders "Demo"')


def test_callable_keyword_completion_uses_registry_signature_metadata() -> None:
    result = analyze("@workflow demo\n@step pause\n  sleep \n")

    items = completions(result, 2, 8)
    milliseconds = next(item for item in items if item["label"] == "ms=")

    assert str(milliseconds["detail"]).startswith("sleep(")
    assert milliseconds["kind"] == "parameter"


def test_canonical_preflight_reports_a_cycle_without_running_a_workflow() -> None:
    result = analyze(
        "@workflow demo\n@step first <- second\n  sleep 1\n@step second <- first\n  sleep 1\n"
    )

    assert any(
        item.code == "SCLPL400" and "loop" in item.message.lower() for item in result.diagnostics
    )


def test_duplicate_definition_and_typo_diagnostics_select_the_smallest_token() -> None:
    result = analyze("@workflow demo\n@step one\n  sleep 1\n@step one\n  sleep 1\n")
    duplicate = next(item for item in result.diagnostics if item.message == "duplicate step 'one'")
    assert (duplicate.range.start_line, duplicate.range.start_character) == (3, 6)

    typo = analyze("@workflow demo\n@ouput report:jsno\n")
    directive = next(item for item in typo.diagnostics if item.code == "SCLPL100")
    assert "output" in directive.remedies[0]
    assert directive.range.start_character == 0


def test_project_auth_profiles_are_names_only_completion_values(tmp_path: Path) -> None:
    (tmp_path / "sclpl.toml").write_text(
        "[project]\n"
        "name = 'demo'\n"
        "[environments.default]\n"
        "[auth.reporting]\n"
        "type = 'bearer'\n"
        "secret = 'TOKEN'\n",
        encoding="utf-8",
    )
    result = analyze("@workflow demo\n@step fetch\n  get https://example.test\n  auth \n")

    labels = {str(item["label"]) for item in completions(result, 3, 7, Path(tmp_path))}
    assert "reporting" in labels
    assert "TOKEN" not in labels


def test_malformed_plugin_metadata_is_a_bounded_passive_warning(tmp_path: Path) -> None:
    plugin = tmp_path / "plugins" / "broken"
    plugin.mkdir(parents=True)
    (plugin / "plugin.toml").write_text("[plugin\n", encoding="utf-8")

    result = analyze("@workflow demo\n@step wait\n  sleep 1\n", workspace=tmp_path)

    warning = next(item for item in result.diagnostics if item.code == "SCLPL700")
    assert warning.severity == "warning"
    assert "broken" in warning.message


def test_plugin_manifest_signature_is_available_without_importing_plugin_code(
    tmp_path: Path,
) -> None:
    plugin = tmp_path / "plugins" / "editor-signature-fixture"
    plugin.mkdir(parents=True)
    (plugin / "plugin.toml").write_text(
        "[plugin]\n"
        "name = 'editor-signature-fixture'\n"
        "module = 'must_not_be_imported'\n"
        "[[function]]\n"
        "name = 'plugin_sleep'\n"
        "summary = 'Pause through a plugin.'\n"
        "signature = 'plugin_sleep(milliseconds, jitter=0)'\n"
        "parameters = ['milliseconds', 'jitter']\n",
        encoding="utf-8",
    )

    signature, summary, parameters, builtin = callable_metadata(tmp_path)["plugin_sleep"]

    assert signature == "plugin_sleep(milliseconds, jitter=0)"
    assert summary == "Pause through a plugin."
    assert parameters == ("milliseconds", "jitter")
    assert not builtin


def test_unterminated_string_range_starts_at_the_opening_quote() -> None:
    result = analyze('@workflow "unfinished\n')
    problem = next(item for item in result.diagnostics if "unterminated string" in item.message)

    assert (problem.range.start_line, problem.range.start_character) == (0, 10)


def test_foreach_binding_is_scoped_for_diagnostics_and_reference_completion() -> None:
    source = """@workflow demo
@input rows:json
@step loop
  foreach @rows as row
    step write
      save_json @row
"""
    result = analyze(source)

    assert not any("@row" in issue.message for issue in result.diagnostics)
    labels = {str(item["label"]) for item in completions(result, 5, 18)}
    assert "row" in labels


def test_registered_function_argument_shape_is_checked_without_invocation() -> None:
    result = analyze("@workflow demo\n@step pause\n  sleep 1 miliseconds=2\n")

    issue = next(item for item in result.diagnostics if "has no argument" in item.message)
    assert issue.code == "SCLPL500"
    assert (issue.range.start_line, issue.range.start_character) == (2, 10)
