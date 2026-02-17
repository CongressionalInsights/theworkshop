#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

# Allow importing TheWorkshop helpers from the scripts directory.
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from twlib import codexbar_cost_snapshot  # noqa: E402


def main() -> None:
    tmp = tempfile.TemporaryDirectory(prefix="theworkshop-token-snapshot-")
    codex_home = Path(tmp.name).resolve()
    session_id = "019c58b3-aab3-7c53-aa4e-f4ec9dc63c03"
    sessions_dir = codex_home / "sessions" / "2026" / "02" / "16"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    log_path = sessions_dir / f"rollout-2026-02-16T10-00-00-{session_id}.jsonl"

    lines = [
        {
            "timestamp": "2026-02-16T10:00:00.000Z",
            "type": "turn_context",
            "payload": {"model": "gpt-5.3-codex"},
        },
        {"timestamp": "2026-02-16T10:00:00.000Z", "type": "event_msg", "payload": {"type": "other"}},
        {"timestamp": "2026-02-16T10:00:01.000Z", "type": "event_msg", "payload": {"type": "token_count", "info": None}},
        {
            "timestamp": "2026-02-16T10:00:02.000Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": 1000,
                        "cached_input_tokens": 100,
                        "output_tokens": 200,
                        "reasoning_output_tokens": 50,
                        "total_tokens": 1200,
                    },
                    "last_token_usage": {
                        "input_tokens": 200,
                        "cached_input_tokens": 20,
                        "output_tokens": 40,
                        "reasoning_output_tokens": 10,
                        "total_tokens": 240,
                    },
                    "model_context_window": 258400,
                },
                "rate_limits": {
                    "limit_id": "codex_bengalfox",
                    "limit_name": "GPT-5.3-Codex-Spark",
                    "plan_type": "pro",
                    "credits": {
                        "has_credits": False,
                        "unlimited": False,
                        "balance": None,
                    },
                },
            },
        },
    ]
    log_path.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")

    old_codex_home = os.environ.get("CODEX_HOME")
    old_thread = os.environ.get("CODEX_THREAD_ID")
    old_path = os.environ.get("PATH")
    try:
        os.environ["CODEX_HOME"] = str(codex_home)
        os.environ["CODEX_THREAD_ID"] = session_id
        # Force fallback by making codexbar undiscoverable in this test.
        os.environ["PATH"] = ""

        snap = codexbar_cost_snapshot("codex")
    finally:
        if old_codex_home is None:
            os.environ.pop("CODEX_HOME", None)
        else:
            os.environ["CODEX_HOME"] = old_codex_home
        if old_thread is None:
            os.environ.pop("CODEX_THREAD_ID", None)
        else:
            os.environ["CODEX_THREAD_ID"] = old_thread
        if old_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = old_path

    if not snap:
        raise RuntimeError("Expected token snapshot fallback payload, got None")
    if str(snap.get("source") or "") != "codex_session_logs":
        raise RuntimeError(f"Expected source=codex_session_logs, got {snap.get('source')!r}")
    if int(snap.get("sessionTokens") or 0) != 1200:
        raise RuntimeError(f"Expected sessionTokens=1200, got {snap.get('sessionTokens')!r}")
    if int(((snap.get("lastTokenUsage") or {}).get("total_tokens") or 0)) != 240:
        raise RuntimeError(f"Expected lastTokenUsage.total_tokens=240, got {snap.get('lastTokenUsage')!r}")
    if int(snap.get("modelContextWindow") or 0) != 258400:
        raise RuntimeError(f"Expected modelContextWindow=258400, got {snap.get('modelContextWindow')!r}")
    if str(snap.get("detectedModel") or "") != "gpt-5.3-codex":
        raise RuntimeError(f"Expected detectedModel=gpt-5.3-codex, got {snap.get('detectedModel')!r}")
    if str(snap.get("rateLimitId") or "") != "codex_bengalfox":
        raise RuntimeError(f"Expected rateLimitId=codex_bengalfox, got {snap.get('rateLimitId')!r}")
    if str(snap.get("rateLimitName") or "") != "GPT-5.3-Codex-Spark":
        raise RuntimeError(f"Expected rateLimitName=GPT-5.3-Codex-Spark, got {snap.get('rateLimitName')!r}")
    if str(snap.get("ratePlanType") or "") != "pro":
        raise RuntimeError(f"Expected ratePlanType=pro, got {snap.get('ratePlanType')!r}")
    if snap.get("rateCreditsHasCredits") is not False:
        raise RuntimeError(f"Expected rateCreditsHasCredits=False, got {snap.get('rateCreditsHasCredits')!r}")
    if snap.get("rateCreditsUnlimited") is not False:
        raise RuntimeError(f"Expected rateCreditsUnlimited=False, got {snap.get('rateCreditsUnlimited')!r}")
    raw_limits = snap.get("rateLimitsRaw")
    if not isinstance(raw_limits, dict):
        raise RuntimeError(f"Expected rateLimitsRaw dict, got {type(raw_limits).__name__}")
    if str(raw_limits.get("limit_id") or "") != "codex_bengalfox":
        raise RuntimeError(f"Expected rateLimitsRaw.limit_id=codex_bengalfox, got {raw_limits.get('limit_id')!r}")
    if str(snap.get("tokenTimestamp") or "") != "2026-02-16T10:00:02.000Z":
        raise RuntimeError(f"Expected tokenTimestamp from latest token_count event, got {snap.get('tokenTimestamp')!r}")

    print("TOKEN SNAPSHOT TEST PASSED")
    print(str(log_path))
    tmp.cleanup()


if __name__ == "__main__":
    main()
