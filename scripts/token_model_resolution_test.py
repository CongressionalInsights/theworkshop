#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from twlib import resolve_rate_model  # noqa: E402


def main() -> None:
    rates = {
        "fallback_model": "gpt-5.3-codex",
        "models": {
            "gpt-5.3-codex": {"usd_per_1m": {"input": 1.5, "cached_input": 0.15, "output": 8.0}},
            "gpt-5.3-codex-spark": {"usd_per_1m": {"input": 1.25, "cached_input": 0.125, "output": 6.0}},
        },
        "aliases": {
            "codex_bengalfox": "gpt-5.3-codex-spark",
            "gpt-5.3-codex spark": "gpt-5.3-codex-spark",
        },
    }

    m1, reason1, c1 = resolve_rate_model({"detectedModel": "gpt-5.3-codex"}, rates)
    if m1 != "gpt-5.3-codex" or c1 != "medium":
        raise RuntimeError(f"Expected direct model match, got model={m1!r} confidence={c1!r} reason={reason1!r}")

    m2, reason2, c2 = resolve_rate_model({"rateLimitId": "codex_bengalfox"}, rates)
    if m2 != "gpt-5.3-codex-spark" or c2 != "medium":
        raise RuntimeError(f"Expected alias model match, got model={m2!r} confidence={c2!r} reason={reason2!r}")

    m3, reason3, c3 = resolve_rate_model({"detectedModel": "unknown-model"}, rates)
    if m3 != "gpt-5.3-codex" or c3 != "low":
        raise RuntimeError(f"Expected fallback model match, got model={m3!r} confidence={c3!r} reason={reason3!r}")

    print("TOKEN MODEL RESOLUTION TEST PASSED")


if __name__ == "__main__":
    main()
