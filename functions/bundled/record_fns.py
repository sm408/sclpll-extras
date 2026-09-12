"""Record-level helpers that make common cleanup pipelines short.

The table functions already cover joins, grouping, and file formats. This module fills
the row-shaping gap: pick values, keep matching rows, fill missing fields, and add a
stable row number. Each function accepts either records or a Table and returns the same
kind where that is useful.
"""

from __future__ import annotations

from typing import Any

from sclpl.ext.functions import function
from sclpl.tables import Table
from sclpl.tables.flatten import records_of


@function("pluck", builtin=True)
def pluck(data: Any, column: str, *, default: Any = None) -> list[Any]:
    """Return one column as a list, preserving row order."""
    return [row.get(column, default) for row in records_of(data)]


@function("filter_rows", builtin=True)
def filter_rows(
    data: Any,
    column: str,
    *,
    equals: Any = None,
    contains: Any = None,
    minimum: float | None = None,
    maximum: float | None = None,
) -> Any:
    """Keep rows whose column matches the supplied checks."""
    rows = [
        row
        for row in records_of(data)
        if _matches(row.get(column), equals, contains, minimum, maximum)
    ]
    return Table.from_records(rows) if isinstance(data, Table) else rows


@function("fill_nulls", builtin=True)
def fill_nulls(data: Any, defaults: dict[str, Any]) -> Any:
    """Replace null or missing fields with defaults."""
    rows: list[dict[str, Any]] = []
    for row in records_of(data):
        filled = dict(row)
        for column, value in defaults.items():
            if filled.get(column) is None:
                filled[column] = value
        rows.append(filled)
    return Table.from_records(rows) if isinstance(data, Table) else rows


@function("row_number", builtin=True)
def row_number(data: Any, *, column: str = "row_number", start: int = 1) -> Any:
    """Add a stable row number column."""
    rows = []
    for offset, row in enumerate(records_of(data), start=start):
        numbered = dict(row)
        numbered[column] = offset
        rows.append(numbered)
    return Table.from_records(rows) if isinstance(data, Table) else rows


def _matches(
    value: Any,
    equals: Any,
    contains: Any,
    minimum: float | None,
    maximum: float | None,
) -> bool:
    if equals is not None and value != equals:
        return False
    if contains is not None and not _contains(value, contains):
        return False
    if minimum is not None and not _bounded(value, minimum, lower=True):
        return False
    return not (maximum is not None and not _bounded(value, maximum, lower=False))


def _contains(value: Any, needle: Any) -> bool:
    if isinstance(value, str):
        return str(needle) in value
    if isinstance(value, (list, tuple, set)):
        return needle in value
    return False


def _bounded(value: Any, bound: float, *, lower: bool) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return bool(value >= bound if lower else value <= bound)
