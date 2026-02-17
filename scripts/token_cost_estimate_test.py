#!/usr/bin/env python3
from __future__ import annotations

import math
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from twlib import estimate_usd_from_tokens  # noqa: E402


def assert_close(actual: float, expected: float, eps: float = 1e-9) -> None:
    if math.fabs(actual - expected) > eps:
        raise RuntimeError(f"Expected {expected}, got {actual}")


def main() -> None:
    usage = {
        "input_tokens": 1000,
        "cached_input_tokens": 200,
        "output_tokens": 300,
        "reasoning_output_tokens": 100,
        "total_tokens": 1400,
    }
    rates = {
        "usd_per_1m": {
            "input": 2.0,
            "cached_input": 0.2,
            "output": 8.0,
            "reasoning_output": 10.0,
        }
    }
    out = estimate_usd_from_tokens(usage, rates)
    expected = ((800 * 2.0) + (200 * 0.2) + (300 * 8.0) + (100 * 10.0)) / 1_000_000.0
    assert_close(float(out.get("total_cost_usd") or 0.0), round(expected, 6), eps=1e-6)

    # reasoning_output falls back to output when missing.
    out2 = estimate_usd_from_tokens(
        usage,
        {"usd_per_1m": {"input": 2.0, "cached_input": 0.2, "output": 8.0}},
    )
    expected2 = ((800 * 2.0) + (200 * 0.2) + (300 * 8.0) + (100 * 8.0)) / 1_000_000.0
    assert_close(float(out2.get("total_cost_usd") or 0.0), round(expected2, 6), eps=1e-6)

    print("TOKEN COST ESTIMATE TEST PASSED")


if __name__ == "__main__":
    main()
