"""The built-in function catalogue.

Importing this registers every built-in. The imports look unused and are not: the
`@function` decorators run on import, which is the registration.
"""

from __future__ import annotations

from sclpl.functions import (
    control_fns,
    diagnostics,
    io_fns,
    python_fns,
    record_fns,
    secrets_fns,
    shape_fns,
)

__all__ = [
    "control_fns",
    "diagnostics",
    "io_fns",
    "python_fns",
    "record_fns",
    "secrets_fns",
    "shape_fns",
]
