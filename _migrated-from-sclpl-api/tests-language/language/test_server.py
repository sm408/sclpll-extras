from __future__ import annotations

from pathlib import Path

from sclpl.language.analysis import analyze
from sclpl.language.server import (
    AnalysisStore,
    _lexical_hover,
    _python_script_location,
    uri_to_path,
)


def test_analysis_store_caches_versions_and_isolates_workspace_roots(tmp_path: Path) -> None:
    root = tmp_path / "one"
    root.mkdir()
    child = root / "workflow.sclpll"
    uri = child.as_uri()
    store = AnalysisStore()
    store.workspace_roots = (root,)

    first = store.analyze(uri, "@workflow one\n@step wait\n  sleep 1\n", 1)
    second = store.analyze(uri, "@workflow one\n@step wait\n  sleep 1\n", 1)

    assert first is second
    assert store.workspace_for(uri) == root
    assert uri_to_path(uri) == child


def test_analysis_store_uses_the_deepest_matching_multi_root_workspace(tmp_path: Path) -> None:
    outer = tmp_path / "outer"
    inner = outer / "nested-project"
    document = inner / "workflow.sclpll"
    inner.mkdir(parents=True)
    store = AnalysisStore()
    store.workspace_roots = (outer, inner)

    assert store.workspace_for(document.as_uri()) == inner


def test_lexical_hover_uses_canonical_vocabulary_when_no_symbol_is_present() -> None:
    analysis = analyze(
        "@workflow demo\n@input data:json\n@step fetch\n  get @fetch.status == 200\n"
    )

    directive = _lexical_hover(analysis, 0, 1)
    format_hover = _lexical_hover(analysis, 1, 13)
    method = _lexical_hover(analysis, 3, 3)

    assert directive is not None and directive[0] == "Directive"
    assert format_hover is not None and format_hover[0] == "Format"
    assert method is not None and method[0] == "HTTP method"


def test_literal_python_script_definition_stays_within_workspace(tmp_path: Path) -> None:
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    target = scripts / "score.py"
    target.write_text("print('score')\n", encoding="utf-8")
    analysis = analyze('@workflow demo\n@step score\n  python "scripts/score.py"\n')

    assert _python_script_location(analysis, 2, 12, tmp_path) == target
    assert _python_script_location(analysis, 2, 3, tmp_path) is None
