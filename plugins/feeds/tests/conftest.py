from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

# Test the package in this directory, not whatever `feeds` may be installed.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from feeds import http  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(autouse=True)
def offline() -> Iterator[None]:
    """No test touches the network; each starts with an empty robots cache."""
    http.clear_robots_cache()
    saved = http.TRANSPORT

    def refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected network call to {request.url}")

    http.TRANSPORT = httpx.MockTransport(refuse)
    yield
    http.TRANSPORT = saved
    http.clear_robots_cache()


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()
