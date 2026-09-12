"""Reading and writing files.

`save_csv` is the reference behaviour for flattening (SPEC section 10): nested objects
become underscore-joined columns, arrays are encoded, and the column order is stable
across runs. Everything else here follows the same rules through `tables/io.py`.

Every writer returns the path it wrote. A step that saves a file usually has nothing
else to hand downstream, and returning the path makes `@save.path` available to a later
step -- an upload, a notification, a checksum.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sclpl.errors import ValidationError
from sclpl.ext.functions import function
from sclpl.tables import Table, io
from sclpl.tables.flatten import flatten_records, records_of

# -- writing ---------------------------------------------------------------------


@function("save_csv", builtin=True)
def save_csv(
    data: Any,
    path: str,
    *,
    sep: str = "_",
    explode: str | None = None,
    columns: str = "union",
) -> str:
    """Write records to CSV, flattening nested objects into underscore columns."""
    return str(io.write(data, Path(path), "csv", sep=sep, explode=explode, columns=columns))


@function("save_json", builtin=True)
def save_json(data: Any, path: str, *, indent: int = 2) -> str:
    """Write a value as JSON, preserving its nesting."""
    return str(io.write(data, Path(path), "json", indent=indent))


@function("save_ndjson", builtin=True)
def save_ndjson(data: Any, path: str) -> str:
    """Write records as newline-delimited JSON, one object per line."""
    return str(io.write(data, Path(path), "ndjson"))


@function("save_parquet", builtin=True)
def save_parquet(data: Any, path: str) -> str:
    """Write records to Parquet: columnar, compressed, and typed."""
    return str(io.write(data, Path(path), "parquet"))


@function("save_excel", builtin=True)
def save_excel(data: Any, path: str, *, sheet: str = "Sheet1") -> str:
    """Write records to an Excel workbook."""
    return str(io.write(data, Path(path), "xlsx", sheet_name=sheet))


@function("save", builtin=True)
def save(data: Any, path: str) -> str:
    """Write a value, choosing the format from the file extension."""
    return str(io.write(data, Path(path)))


# -- reading ---------------------------------------------------------------------


@function("read_csv", builtin=True)
def read_csv(path: str, **options: Any) -> Table:
    """Read a CSV file into a table."""
    result = io.read(Path(path), "csv", **options)
    return result if isinstance(result, Table) else Table.from_records([])


@function("read_json", builtin=True)
def read_json(path: str) -> Any:
    """Read a JSON file, keeping whatever shape it holds."""
    return io.read(Path(path), "json")


@function("read_ndjson", builtin=True)
def read_ndjson(path: str) -> Any:
    """Read newline-delimited JSON into a list of objects."""
    return io.read(Path(path), "ndjson")


@function("read_parquet", builtin=True)
def read_parquet(path: str) -> Any:
    """Read a Parquet file into a table."""
    return io.read(Path(path), "parquet")


@function("read_excel", builtin=True)
def read_excel(path: str, *, sheet: str | int = 0) -> Any:
    """Read a sheet of an Excel workbook into a table."""
    return io.read(Path(path), "xlsx", sheet_name=sheet)


@function("read", builtin=True)
def read_any(path: str) -> Any:
    """Read a file, choosing the format from the extension."""
    return io.read(Path(path))


@function("glob_read", builtin=True)
def glob_read(pattern: str, *, concat: bool = True) -> Any:
    """Read every file matching a pattern, concatenated by default."""
    base = Path(pattern)
    root = base.parent if str(base.parent) != "." else Path()
    matches = sorted(root.glob(base.name))
    if not matches:
        raise ValidationError(
            f"the pattern {pattern!r} matched no files",
            remedies=["check the directory, or quote the pattern so the shell leaves it alone"],
        )

    parts = [io.read(path) for path in matches]
    if not concat:
        return parts

    tables = [part for part in parts if isinstance(part, Table)]
    if len(tables) == len(parts) and tables:
        combined = tables[0]
        for table in tables[1:]:
            combined = combined.concat(table)
        return combined

    rows: list[Any] = []
    for part in parts:
        rows.extend(part if isinstance(part, list) else [part])
    return rows


@function("convert", builtin=True)
def convert(source: str, target: str) -> str:
    """Read one file and write it out in another format."""
    return str(io.write(io.read(Path(source)), Path(target)))


# -- shaping ---------------------------------------------------------------------


@function("flatten", builtin=True)
def flatten(
    data: Any,
    *,
    sep: str = "_",
    explode: str | None = None,
    columns: str = "union",
    max_depth: int = 12,
    depth: int = 1,
) -> Any:
    """Flatten nested objects into underscore-joined columns, or nested lists into one.

    A list of lists has no columns to name, so it gets the list meaning, one level at a
    time unless `depth` says otherwise; anything with records gets the column meaning.
    Both are "flatten" to the person writing it.
    """
    if isinstance(data, list) and any(isinstance(item, (list, tuple)) for item in data):
        from sclpl.expr.ops.coll import flatten_lists

        return flatten_lists(data, depth)

    records = _records(data)
    return flatten_records(
        records,
        sep=sep,
        explode=explode,
        columns=columns,  # type: ignore[arg-type]
        max_depth=max_depth,
    )


@function("explode", builtin=True)
def explode(data: Any, field: str) -> Any:
    """Turn each element of an array field into its own row."""
    return flatten_records(_records(data), explode=field)


@function("to_table", builtin=True)
def to_table(data: Any) -> Table:
    """Convert records into a table."""
    from sclpl.tables import as_table

    if isinstance(data, list) and data and isinstance(data[0], dict):
        return Table.from_records(flatten_records(data))
    return as_table(data)


@function("normalize", builtin=True)
def normalize(data: Any, *, sep: str = "_") -> Any:
    """Flatten and align records so every one has the same fields."""
    return flatten_records(_records(data), sep=sep, columns="union")


def _records(data: Any) -> list[dict[str, Any]]:
    """Get a list of objects out of whatever a step produced.

    One line, because `records_of` is the definition -- including for a `Table`, which
    it recognises by behaviour rather than by type.
    """
    return records_of(data)
