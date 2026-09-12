"""A normal Python script used by 13-python-script.sclpll.

It intentionally knows nothing about SCLPLL. JSON stdin/stdout is the tiny process boundary
that lets it participate in a workflow while remaining runnable with Python on its own.
"""

from __future__ import annotations

import argparse
import json
import sys


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--multiplier", type=float, default=1.0)
    options = parser.parse_args()
    rows = json.load(sys.stdin)
    json.dump(
        [{"id": row["id"], "score": row["amount"] * options.multiplier} for row in rows],
        sys.stdout,
    )


if __name__ == "__main__":
    main()
