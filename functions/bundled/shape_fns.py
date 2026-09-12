"""Combining and reshaping: join, merge, concat, sort, group, pivot.

These work on tables and on lists of objects alike. A workflow author should not have
to know which one a previous step produced, so every function here coerces and returns
the same kind it was given.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sclpl.errors import TypeDispatchError, ValidationError, did_you_mean
from sclpl.ext.functions import function
from sclpl.tables import Table
from sclpl.tables.flatten import flatten_records


@function("join", builtin=True)
def join(
    left: Any, right: Any = ",", on: str | list[str] | None = None, *, how: str = "inner"
) -> Any:
    """Join two tables on shared columns, or join a list into a string.

    One name, two shapes, because that is how both are spelled everywhere else:
    `join(@names, ', ')` and `join(@orders, @customers, 'id')`. The first argument is a
    list either way, so the dispatch table cannot separate them -- the second argument
    does. A string on the right with no key means the string form.
    """
    if on is None and isinstance(right, str):
        from sclpl.expr.ops.string import join_text

        return join_text(left, right)

    if on is None:
        raise ValidationError(
            "join() of two tables needs the column to join on",
            remedies=["join(@left, @right, 'id')", "join(@names, ', ') joins a list into a string"],
        )
    if how not in ("inner", "left", "right", "outer"):
        raise ValidationError(
            f"unknown join type {how!r}",
            remedies=["use one of: inner, left, right, outer"],
        )
    keys = [on] if isinstance(on, str) else list(on)
    return _table(left).join(_table(right), keys, how)


@function("merge", builtin=True)
def merge(first: Any, *rest: Any) -> Any:
    """Merge records or objects; later values win on a shared key."""
    if isinstance(first, dict) and all(isinstance(item, dict) for item in rest):
        from sclpl.expr.ops.coll import merge_objects

        return merge_objects(first, *rest)
    return concat(first, *rest)


@function("concat", builtin=True)
def concat(first: Any, *rest: Any) -> Any:
    """Stack tables or lists of records end to end."""
    if not rest:
        return first
    if isinstance(first, Table) or any(isinstance(item, Table) for item in rest):
        combined = _table(first)
        for item in rest:
            combined = combined.concat(_table(item))
        return combined
    rows = list(_records(first))
    for item in rest:
        rows.extend(_records(item))
    return rows


@function("sort_by", builtin=True)
def sort_by(data: Any, by: str | list[str], *, descending: bool = False) -> Any:
    """Sort records by one or more columns."""
    keys = [by] if isinstance(by, str) else list(by)
    if isinstance(data, Table):
        _check_columns(data.columns, keys)
        return data.sort(keys, descending)
    rows = _records(data)
    if rows:
        _check_columns(list(rows[0]), keys)

    def ordering(row: dict[str, Any]) -> tuple[Any, ...]:
        return tuple(_key(row.get(key)) for key in keys)

    return sorted(rows, key=ordering, reverse=descending)


@function("dedupe", builtin=True)
def dedupe(data: Any, *, by: str | list[str] | None = None) -> Any:
    """Remove duplicate records, optionally comparing only some columns."""
    subset = [by] if isinstance(by, str) else (list(by) if by else None)
    if isinstance(data, Table):
        return data.dedupe(subset)

    seen: set[Any] = set()
    out: list[dict[str, Any]] = []
    for row in _records(data):
        marker = tuple(row.get(key) for key in subset) if subset else tuple(sorted(row.items()))
        try:
            hash(marker)
        except TypeError:
            marker = repr(marker)  # type: ignore[assignment]
        if marker not in seen:
            seen.add(marker)
            out.append(row)
    return out


@function("group_agg", builtin=True)
def group_agg(data: Any, by: str | list[str], *, agg: dict[str, str] | None = None) -> Any:
    """Group records and aggregate the other columns.

    `agg` maps a column to one of count, sum, min, max, avg, first, last. Without it,
    every group is reduced to a count -- which is what "group by" alone usually means.
    """
    keys = [by] if isinstance(by, str) else list(by)
    rows = _records(data)
    if rows:
        _check_columns(list(rows[0]), keys)

    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in rows:
        marker = tuple(row.get(key) for key in keys)
        groups.setdefault(marker, []).append(row)

    out: list[dict[str, Any]] = []
    for marker, members in groups.items():
        record = dict(zip(keys, marker, strict=False))
        if not agg:
            record["count"] = len(members)
        else:
            for column, how in agg.items():
                record[f"{column}_{how}"] = _aggregate(members, column, how)
        out.append(record)
    return Table.from_records(out) if isinstance(data, Table) else out


@function("pivot", builtin=True)
def pivot(data: Any, *, index: str, column: str, value: str) -> Table:
    """Turn distinct values of one column into columns of their own."""
    rows = _records(data)
    if rows:
        _check_columns(list(rows[0]), [index, column, value])

    pivoted: dict[Any, dict[str, Any]] = {}
    for row in rows:
        key = row.get(index)
        record = pivoted.setdefault(key, {index: key})
        record[str(row.get(column))] = row.get(value)
    return Table.from_records(list(pivoted.values()))


@function("select", builtin=True)
def select(data: Any, *columns: str) -> Any:
    """Keep only the named columns."""
    wanted = _flatten_names(columns)
    if isinstance(data, Table):
        return data.select(wanted)
    return [{key: row.get(key) for key in wanted} for row in _records(data)]


@function("rename", builtin=True)
def rename(data: Any, mapping: dict[str, str]) -> Any:
    """Rename columns."""
    if isinstance(data, Table):
        return data.rename(mapping)
    return [{mapping.get(key, key): value for key, value in row.items()} for row in _records(data)]


@function("head", builtin=True)
def head(data: Any, n: int = 10) -> Any:
    """The first n records."""
    if isinstance(data, Table):
        return data.head(n)
    return _records(data)[:n]


@function("infer_schema", builtin=True)
def infer_schema_fn(data: Any) -> dict[str, str]:
    """The column types the records imply."""
    from sclpl.tables import infer_schema

    if isinstance(data, Table):
        return data.dtypes()
    return infer_schema(_records(data))


@function("cast_schema", builtin=True)
def cast_schema(data: Any, schema: dict[str, str]) -> Any:
    """Coerce columns to the named types, leaving unlisted ones alone."""
    casters: dict[str, Callable[[Any], Any]] = {
        "integer": _to_int,
        "number": _to_float,
        "boolean": _to_bool,
        "string": _to_str,
    }
    unknown = [name for name in schema.values() if name not in casters]
    if unknown:
        raise ValidationError(
            f"unknown type {unknown[0]!r} in the schema",
            remedies=[f"use one of: {', '.join(casters)}"],
        )

    rows = []
    for row in _records(data):
        cast = dict(row)
        for column, wanted in schema.items():
            if column in cast:
                cast[column] = casters[wanted](cast[column])
        rows.append(cast)
    return Table.from_records(rows) if isinstance(data, Table) else rows


# -- helpers ---------------------------------------------------------------------


def _table(value: Any) -> Table:
    from sclpl.tables import as_table

    if isinstance(value, Table):
        return value
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return Table.from_records(flatten_records(value))
    return as_table(value)


def _records(data: Any) -> list[dict[str, Any]]:
    from sclpl.functions.io_fns import _records as shared

    return shared(data)


def _check_columns(available: list[str], wanted: list[str]) -> None:
    for column in wanted:
        if column in available:
            continue
        remedies = []
        suggestion = did_you_mean(column, available)
        if suggestion:
            remedies.append(suggestion)
        remedies.append(f"columns: {', '.join(available[:8])}")
        raise ValidationError(f"no column named {column!r}", remedies=remedies)


def _aggregate(rows: list[dict[str, Any]], column: str, how: str) -> Any:
    values: list[Any] = [row[column] for row in rows if row.get(column) is not None]
    match how:
        case "count":
            return len(values)
        case "sum":
            return sum(_numbers(values, column, how))
        case "avg":
            numbers = _numbers(values, column, how)
            return sum(numbers) / len(numbers) if numbers else None
        case "min":
            return min(values) if values else None
        case "max":
            return max(values) if values else None
        case "first":
            return values[0] if values else None
        case "last":
            return values[-1] if values else None
        case _:
            raise ValidationError(
                f"unknown aggregate {how!r}",
                remedies=["use one of: count, sum, avg, min, max, first, last"],
            )


def _numbers(values: list[Any], column: str, how: str) -> list[float]:
    out: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeDispatchError(
                f"{how} of {column!r} found {type(value).__name__} where it needed a number",
                remedies=[f"cast it first: cast_schema(@x, {{'{column}': 'number'}})"],
            )
        out.append(value)
    return out


def _key(value: Any) -> tuple[int, Any]:
    """Sort key that tolerates nulls and mixed types rather than raising."""
    if value is None:
        return (0, "")
    if isinstance(value, bool):
        return (1, int(value))
    if isinstance(value, (int, float)):
        return (1, value)
    return (2, str(value))


def _flatten_names(names: tuple[Any, ...]) -> list[str]:
    if len(names) == 1 and isinstance(names[0], (list, tuple)):
        return [str(name) for name in names[0]]
    return [str(name) for name in names]


def _to_int(value: Any) -> Any:
    from sclpl.expr.ops.cast import to_int

    return None if value is None else to_int(value, None)


def _to_float(value: Any) -> Any:
    from sclpl.expr.ops.cast import to_number

    result = to_number(value, None) if value is not None else None
    return float(result) if isinstance(result, (int, float)) else None


def _to_str(value: Any) -> Any:
    return None if value is None else str(value)


def _to_bool(value: Any) -> Any:
    from sclpl.expr.ops.cast import to_bool

    return None if value is None else to_bool(value)
