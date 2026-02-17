#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from twlib import resolve_billing_mode  # noqa: E402


def main() -> None:
    mode, reason, conf = resolve_billing_mode(
        {
            "source": "codex_session_logs",
            "rateLimitId": "codex_bengalfox",
            "rateLimitName": "GPT-5.3-Codex-Spark",
            "detectedModel": "gpt-5.3-codex",
        },
        None,
    )
    if mode != "subscription_auth":
        raise RuntimeError(f"Expected subscription_auth, got mode={mode!r} reason={reason!r}")
    if conf not in {"high", "medium"}:
        raise RuntimeError(f"Expected confidence high|medium, got {conf!r}")

    mode2, reason2, conf2 = resolve_billing_mode({}, 1.2345)
    if mode2 != "metered_api" or conf2 != "high":
        raise RuntimeError(f"Expected metered_api/high for exact cost, got {mode2!r}/{conf2!r} ({reason2!r})")

    mode3, reason3, conf3 = resolve_billing_mode({"source": "none"}, None)
    if mode3 != "unknown" or conf3 != "low":
        raise RuntimeError(f"Expected unknown/low fallback, got {mode3!r}/{conf3!r} ({reason3!r})")

    old = os.environ.get("THEWORKSHOP_BILLING_MODE")
    try:
        os.environ["THEWORKSHOP_BILLING_MODE"] = "subscription_auth"
        mode4, reason4, conf4 = resolve_billing_mode({"source": "none"}, None)
    finally:
        if old is None:
            os.environ.pop("THEWORKSHOP_BILLING_MODE", None)
        else:
            os.environ["THEWORKSHOP_BILLING_MODE"] = old

    if mode4 != "subscription_auth" or conf4 != "high":
        raise RuntimeError(f"Expected env override subscription_auth/high, got {mode4!r}/{conf4!r} ({reason4!r})")

    print("BILLING MODE RESOLUTION TEST PASSED")


if __name__ == "__main__":
    main()
