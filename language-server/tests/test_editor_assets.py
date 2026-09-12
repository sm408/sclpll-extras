from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[2] / "vscode"


def test_vscode_registration_and_textmate_fallback_cover_core_vocabulary() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    grammar = json.loads((ROOT / "syntaxes" / "sclpll.tmLanguage.json").read_text(encoding="utf-8"))

    language = package["contributes"]["languages"][0]
    assert language["id"] == "sclpll"
    assert language["extensions"] == [".sclpll"]
    serialized = json.dumps(grammar)
    for word in (
        "workflow",
        "step",
        "get",
        "foreach",
        "paginate",
        "retry",
        "parquet",
        "interpolation",
    ):
        assert word in serialized


def test_showcase_is_a_valid_canonical_workflow() -> None:
    from sclpl.run.sclpll import parse

    showcase = ROOT / "test" / "fixtures" / "showcase.sclpll"
    document = parse(showcase.read_text(encoding="utf-8"), origin=str(showcase))

    assert document.name == "nightly-orders"
    assert document.step("score") is not None
