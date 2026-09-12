"""Diagnostics: assertions and descriptions of data in flight.

These are what turns a pipeline that ran into a pipeline you can trust. An assertion
that fails exits 4 rather than 1, so a script can tell "the data was wrong" from "the
request failed" -- two problems with entirely different responses.
"""

from __future__ import annotations

from typing import Any

from sclpl.errors import AssertionFailed
from sclpl.ext.functions import function
from sclpl.tables import Table
from sclpl.tables.flatten import infer_schema


@function("assert_schema", builtin=True)
def assert_schema(data: Any, schema: dict[str, str], *, strict: bool = False) -> Any:
    """Check that the records have the expected columns and types.

    Returns the data unchanged so it can sit mid-pipeline. `strict` also rejects extra
    columns; by default an extra column is fine, because an API adding a field should
    not break a workflow that ignores it.
    """
    observed = data.dtypes() if isinstance(data, Table) else infer_schema(_records(data))

    missing = [name for name in schema if name not in observed]
    if missing:
        raise AssertionFailed(
            f"missing column{'' if len(missing) == 1 else 's'}: {', '.join(missing)}",
            remedies=[
                f"present: {', '.join(sorted(observed)[:8])}",
                "check the step that produced this, or the flatten separator",
            ],
        )

    wrong = [
        f"{name}: expected {wanted}, found {observed[name]}"
        for name, wanted in schema.items()
        if not _compatible(observed[name], wanted)
    ]
    if wrong:
        raise AssertionFailed(
            "column types do not match the schema",
            remedies=[*wrong, "cast first: cast_schema(@x, {...})"],
        )

    if strict:
        extra = [name for name in observed if name not in schema]
        if extra:
            raise AssertionFailed(
                f"unexpected column{'' if len(extra) == 1 else 's'}: {', '.join(extra)}",
                remedies=["drop strict, or add them to the schema"],
            )
    return data


@function("assert_rowcount", builtin=True)
def assert_rowcount(
    data: Any, *, min: int | None = None, max: int | None = None, exactly: int | None = None
) -> Any:
    """Check how many records there are. Returns the data unchanged."""
    count = data.row_count if isinstance(data, Table) else len(_records(data))

    if exactly is not None and count != exactly:
        raise AssertionFailed(f"expected exactly {exactly} rows, found {count}")
    if min is not None and count < min:
        raise AssertionFailed(
            f"expected at least {min} rows, found {count}",
            remedies=["an empty result often means a filter matched nothing"],
        )
    if max is not None and count > max:
        raise AssertionFailed(f"expected at most {max} rows, found {count}")
    return data


@function("assert_unique", builtin=True)
def assert_unique(data: Any, by: str | list[str]) -> Any:
    """Check that a column, or a combination, has no duplicates."""
    keys = [by] if isinstance(by, str) else list(by)
    seen: dict[tuple[Any, ...], int] = {}
    duplicates: list[tuple[Any, ...]] = []

    for row in _records(data):
        marker = tuple(row.get(key) for key in keys)
        seen[marker] = seen.get(marker, 0) + 1
        if seen[marker] == 2:
            duplicates.append(marker)

    if duplicates:
        shown = ", ".join(
            repr(marker[0] if len(marker) == 1 else marker) for marker in duplicates[:5]
        )
        more = f" (+{len(duplicates) - 5} more)" if len(duplicates) > 5 else ""
        raise AssertionFailed(
            f"{', '.join(keys)} is not unique: {shown}{more}",
            remedies=["dedupe(@x, by='id') if duplicates are expected"],
        )
    return data


@function("assert_no_nulls", builtin=True)
def assert_no_nulls(data: Any, *columns: str) -> Any:
    """Check that the named columns have no missing values."""
    wanted = list(columns) if columns else None
    offenders: dict[str, int] = {}
    for row in _records(data):
        for column in wanted if wanted is not None else list(row):
            if row.get(column) is None:
                offenders[column] = offenders.get(column, 0) + 1
    if offenders:
        detail = ", ".join(f"{name} ({count})" for name, count in sorted(offenders.items()))
        raise AssertionFailed(
            f"null values in: {detail}",
            remedies=["fill them with default(), or drop the rows before asserting"],
        )
    return data


@function("profile", builtin=True)
def profile(data: Any) -> dict[str, Any]:
    """A summary of the data: row count, columns, types, and null counts."""
    rows = _records(data)
    schema = data.dtypes() if isinstance(data, Table) else infer_schema(rows)
    nulls = {name: sum(1 for row in rows if row.get(name) is None) for name in schema}
    return {
        "rows": len(rows),
        "columns": len(schema),
        "schema": schema,
        "nulls": {name: count for name, count in nulls.items() if count},
    }


@function("describe", builtin=True)
def describe(data: Any) -> dict[str, Any]:
    """Per-column statistics: count, nulls, distinct, and min/max where meaningful."""
    rows = _records(data)
    out: dict[str, Any] = {}
    for column in _columns(rows):
        values = [row.get(column) for row in rows]
        present = [value for value in values if value is not None]
        entry: dict[str, Any] = {
            "count": len(present),
            "nulls": len(values) - len(present),
            "distinct": len({_hashable(value) for value in present}),
        }
        numbers = [v for v in present if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if numbers and len(numbers) == len(present):
            entry["min"] = min(numbers)
            entry["max"] = max(numbers)
            entry["mean"] = sum(numbers) / len(numbers)
        out[column] = entry
    return out


@function("sample", builtin=True)
def sample(data: Any, n: int = 5) -> Any:
    """A few records, evenly spaced through the data rather than just the first few.

    Both ends are included. The last row is where a truncated response or a bad final
    page shows up, so a sample that can never reach it is the wrong tool.
    """
    rows = _records(data)
    if n <= 0:
        return []
    if len(rows) <= n:
        return rows
    if n == 1:
        return [rows[0]]
    stride = (len(rows) - 1) / (n - 1)
    return [rows[round(index * stride)] for index in range(n)]


# -- helpers ---------------------------------------------------------------------


def _records(data: Any) -> list[dict[str, Any]]:
    from sclpl.functions.io_fns import _records as shared

    return shared(data)


def _columns(rows: list[dict[str, Any]]) -> list[str]:
    ordered: list[str] = []
    for row in rows:
        for key in row:
            if key not in ordered:
                ordered.append(key)
    return ordered


def _compatible(observed: str, wanted: str) -> bool:
    """Whether an observed type satisfies an expected one.

    An integer column satisfies `number`, and anything satisfies `string`, because
    those widenings never lose information. The reverse does.
    """
    if observed == wanted:
        return True
    if wanted == "number" and observed == "integer":
        return True
    if wanted == "string":
        return True
    return observed == "null"


def _hashable(value: Any) -> Any:
    try:
        hash(value)
    except TypeError:
        return repr(value)
    return value
