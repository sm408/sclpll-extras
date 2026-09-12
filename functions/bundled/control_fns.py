"""Control-flow helpers: pausing a workflow deliberately.

A step that needs to wait on purpose -- spacing out a burst of requests, giving an
eventually-consistent API a moment to catch up -- reaches for this rather than a
bespoke retry/backoff dance built out of `while`.
"""

from __future__ import annotations

import asyncio

from sclpl.errors import ValidationError
from sclpl.ext.functions import function


@function("sleep", builtin=True)
async def sleep(ms: int) -> int:
    """Pause the step for ms milliseconds, then return ms.

    `async def` puts this on the event loop lane, so waiting costs nothing but the
    calling step's own progress -- every other step keeps running while this one does.
    """
    if ms < 0:
        raise ValidationError(
            f"sleep(ms) needs ms >= 0, got {ms}", remedies=["milliseconds, not seconds"]
        )
    await asyncio.sleep(ms / 1000)
    return ms
