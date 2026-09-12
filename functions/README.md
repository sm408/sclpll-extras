# Custom functions

SCLPL can run normal Python scripts through its `python` function. A script remains a normal `.py` file: JSON arrives on stdin and results are written to stdout. It does not need to be a plugin.

[`python-script`](python-script/) is a complete local example, including a hash-pinned script registration and a workflow that calls it. Copy the directory, change the script, recompute its SHA-256, and register a new name in `sclpl.toml`.
