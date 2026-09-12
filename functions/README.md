# Functions

The core SCLPL package continues to ship and register every built-in below. [`bundled/`](bundled/) mirrors the current source in this catalogue; it is not a second installable runtime.

| Area | Available functions |
|---|---|
| Control | `sleep` |
| Diagnostics | `assert_schema`, `assert_rowcount`, `assert_unique`, `assert_no_nulls`, `profile`, `describe`, `sample` |
| I/O and transforms | `save_csv`, `save_json`, `save_ndjson`, `save_parquet`, `save_excel`, `save`, `read_csv`, `read_json`, `read_ndjson`, `read_parquet`, `read_excel`, `read`, `glob_read`, `convert`, `flatten`, `explode`, `to_table`, `normalize` |
| Records | `pluck`, `filter_rows`, `fill_nulls`, `row_number` |
| Secrets | `secret`, `has_secret` |
| Shape | `join`, `merge`, `concat`, `sort_by`, `dedupe`, `group_agg`, `pivot`, `select`, `rename`, `head`, `infer_schema`, `cast_schema` |
| Python scripts | `python` |

[`python-script/`](python-script/) contains the current ordinary-Python function asset. Such scripts receive JSON on stdin and emit JSON to stdout; they do not need to become plugins.
