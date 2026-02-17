#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import tempfile
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from twlib import allocate_project_cost_by_work_item  # noqa: E402


def write_session_log(codex_home: Path, session_id: str, total_tokens: int) -> Path:
    sessions_dir = codex_home / "sessions" / "2026" / "02" / "16"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    log_path = sessions_dir / f"rollout-2026-02-16T10-00-00-{session_id}.jsonl"
    lines = [
        {"timestamp": "2026-02-16T10:00:00.000Z", "type": "turn_context", "payload": {"model": "gpt-5.3-codex"}},
        {
            "timestamp": "2026-02-16T10:00:02.000Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": total_tokens,
                        "cached_input_tokens": int(total_tokens * 0.1),
                        "output_tokens": int(total_tokens * 0.2),
                        "reasoning_output_tokens": int(total_tokens * 0.05),
                        "total_tokens": total_tokens,
                    },
                    "last_token_usage": {"total_tokens": 123},
                    "model_context_window": 258400,
                },
                "rate_limits": {"limit_id": "codex_bengalfox", "limit_name": "GPT-5.3-Codex-Spark"},
            },
        },
    ]
    log_path.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    return log_path


def main() -> None:
    tmp = tempfile.TemporaryDirectory(prefix="theworkshop-cost-allocation-")
    root = Path(tmp.name).resolve()
    project_root = root / "project"
    codex_home = root / "codex_home"
    (project_root / "logs").mkdir(parents=True, exist_ok=True)

    session_id = "019c58b3-aab3-7c53-aa4e-f4ec9dc63c03"
    write_session_log(codex_home, session_id, total_tokens=2000)

    baseline = {
        "schema": "theworkshop.tokenbaseline.v1",
        "session_id": session_id,
        "baseline_tokens": {
            "input_tokens": 1000,
            "cached_input_tokens": 100,
            "output_tokens": 200,
            "reasoning_output_tokens": 50,
            "total_tokens": 1000,
        },
    }
    (project_root / "logs" / "token-baseline.json").write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")

    entries = [
        {"duration_sec": 9, "work_item_id": "WI-A"},
        {"duration_sec": 1, "work_item_id": "WI-A"},
        {"duration_sec": 4, "work_item_id": "WI-B"},
        {"duration_sec": 0, "work_item_id": ""},
    ]
    (project_root / "logs" / "execution.jsonl").write_text(
        "\n".join(json.dumps(x) for x in entries) + "\n",
        encoding="utf-8",
    )

    old_home = os.environ.get("CODEX_HOME")
    old_thread = os.environ.get("CODEX_THREAD_ID")
    old_path = os.environ.get("PATH")
    try:
        os.environ["CODEX_HOME"] = str(codex_home)
        os.environ["CODEX_THREAD_ID"] = session_id
        os.environ["PATH"] = ""  # force codexbar fallback path

        out = allocate_project_cost_by_work_item(project_root, 9.0)
    finally:
        if old_home is None:
            os.environ.pop("CODEX_HOME", None)
        else:
            os.environ["CODEX_HOME"] = old_home
        if old_thread is None:
            os.environ.pop("CODEX_THREAD_ID", None)
        else:
            os.environ["CODEX_THREAD_ID"] = old_thread
        if old_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = old_path

    rows = out.get("by_work_item") or []
    if len(rows) != 2:
        raise RuntimeError(f"Expected two WI rows, got {rows!r}")
    if int(out.get("project_delta_tokens") or 0) != 1000:
        raise RuntimeError(f"Expected project_delta_tokens=1000, got {out.get('project_delta_tokens')!r}")
    if float(out.get("unattributed_cost_usd") or 0.0) <= 0.0:
        raise RuntimeError(f"Expected non-zero unattributed cost, got {out.get('unattributed_cost_usd')!r}")

    wi_a = next((r for r in rows if str(r.get("work_item_id")) == "WI-A"), None)
    wi_b = next((r for r in rows if str(r.get("work_item_id")) == "WI-B"), None)
    if wi_a is None or wi_b is None:
        raise RuntimeError(f"Expected WI-A and WI-B rows, got {rows!r}")
    if float(wi_a.get("estimated_cost_usd") or 0.0) <= float(wi_b.get("estimated_cost_usd") or 0.0):
        raise RuntimeError(f"Expected WI-A cost > WI-B cost, got WI-A={wi_a} WI-B={wi_b}")
    if int(wi_a.get("tokens_allocated") or 0) <= int(wi_b.get("tokens_allocated") or 0):
        raise RuntimeError(f"Expected WI-A tokens > WI-B tokens, got WI-A={wi_a} WI-B={wi_b}")

    print("COST ALLOCATION BY WI TEST PASSED")
    print(str(project_root))
    tmp.cleanup()


if __name__ == "__main__":
    main()
