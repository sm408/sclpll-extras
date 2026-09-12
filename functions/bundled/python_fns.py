"""Run ordinary Python scripts as workflow steps.

The script is deliberately a normal Python program.  It receives its regular command
line arguments unchanged.  When a workflow supplies ``input=...``, SCLPL writes that
value as JSON to standard input; JSON written to standard output becomes the step
value.  A script that does neither remains a perfectly ordinary file-oriented script.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from sclpl.errors import StepFailed, ValidationError
from sclpl.ext.functions import function


@function("python", builtin=True, lane="thread")
def run_python(
    script: str,
    *,
    args: list[str] | None = None,
    input: Any = None,
    cwd: str | None = None,
) -> Any:
    """Run a verified registered Python script; JSON stdin and stdout connect workflow values."""
    return run_path(script, args=args, input=input, cwd=cwd)


def run_path(
    script: str,
    *,
    args: list[str] | None = None,
    input: Any = None,
    cwd: str | None = None,
) -> Any:
    """Run already-authorized local script bytes.

    This is intentionally an internal execution primitive. The workflow runner and
    `sclpl python` resolve a manifest registration and verify its digest before they
    call it; accepting arbitrary paths at those public boundaries would be fail-open.
    """
    path = Path(script)
    if not path.is_file():
        raise ValidationError(
            f"Python script {script!r} does not exist or is not a file",
            remedies=["check the registered script source"],
        )
    if path.suffix.lower() != ".py":
        raise ValidationError(
            f"Python script {script!r} does not end in .py",
            remedies=["pass a normal Python source file"],
        )
    if cwd is not None and not Path(cwd).is_dir():
        raise ValidationError(f"working directory {cwd!r} does not exist or is not a directory")

    try:
        payload = json.dumps(input, default=_json_default) + "\n"
    except (TypeError, ValueError) as error:
        raise ValidationError(
            f"cannot pass the value to {script!r} as JSON: {error}",
            remedies=["pass JSON-shaped data, or save it to a file and pass that path in args"],
        ) from error

    completed = subprocess.run(
        [sys.executable, str(path), *(args or [])],
        input=payload,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        cwd=cwd,
        check=False,
    )
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip() or "no output"
        raise StepFailed(
            f"Python script {script!r} exited with status {completed.returncode}: {detail}",
            remedies=["run the script directly to debug it", "write diagnostics to stderr"],
        )

    output = completed.stdout.strip()
    if not output:
        return None
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return completed.stdout.rstrip("\r\n")


def _json_default(value: Any) -> Any:
    """Keep tables usable at the process boundary without importing their concrete type."""
    to_records = getattr(value, "to_records", None)
    if callable(to_records):
        return to_records()
    raise TypeError(f"{type(value).__name__} is not JSON serializable")
