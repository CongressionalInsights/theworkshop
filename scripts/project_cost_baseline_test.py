#!/usr/bin/env python3
from __future__ import annotations

import json
import tempfile
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from twlib import estimate_project_delta_cost, load_or_init_cost_baseline  # noqa: E402


def make_snapshot(session_id: str, total_tokens: int) -> dict:
    return {
        "sessionId": session_id,
        "totalTokenUsage": {
            "input_tokens": total_tokens,
            "cached_input_tokens": int(total_tokens * 0.1),
            "output_tokens": int(total_tokens * 0.2),
            "reasoning_output_tokens": int(total_tokens * 0.05),
            "total_tokens": total_tokens,
        },
        "detectedModel": "gpt-5.3-codex",
    }


def main() -> None:
    tmp = tempfile.TemporaryDirectory(prefix="theworkshop-cost-baseline-")
    project_root = Path(tmp.name).resolve()
    (project_root / "logs").mkdir(parents=True, exist_ok=True)

    s1 = make_snapshot("session-a", 1000)
    base1 = load_or_init_cost_baseline(project_root, s1)
    if not base1.get("available"):
        raise RuntimeError("Expected baseline to be available after initialization")
    if not (project_root / "logs" / "token-baseline.json").exists():
        raise RuntimeError("Expected baseline file to be created")

    s2 = make_snapshot("session-a", 1800)
    delta = estimate_project_delta_cost(
        s2,
        base1,
        {"usd_per_1m": {"input": 1.0, "cached_input": 0.1, "output": 5.0, "reasoning_output": 5.0}},
    )
    if int(delta.get("project_cost_delta_tokens") or 0) <= 0:
        raise RuntimeError(f"Expected positive project token delta, got {delta!r}")
    if float(delta.get("estimated_project_cost_usd") or 0.0) <= 0.0:
        raise RuntimeError(f"Expected positive estimated project cost, got {delta!r}")

    # Session switch should reset baseline.
    s3 = make_snapshot("session-b", 2100)
    base2 = load_or_init_cost_baseline(project_root, s3)
    if not base2.get("reset"):
        raise RuntimeError(f"Expected baseline reset on session change, got {base2!r}")

    # Baseline file should now reference session-b.
    payload = json.loads((project_root / "logs" / "token-baseline.json").read_text(encoding="utf-8"))
    if str(payload.get("session_id") or "") != "session-b":
        raise RuntimeError(f"Expected session_id=session-b in baseline file, got {payload.get('session_id')!r}")

    print("PROJECT COST BASELINE TEST PASSED")
    print(str(project_root))
    tmp.cleanup()


if __name__ == "__main__":
    main()
