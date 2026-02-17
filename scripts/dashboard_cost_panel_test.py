#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent


def run(cmd: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, text=True, capture_output=True, env=env)
    if proc.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            f"  cmd={' '.join(cmd)}\n"
            f"  exit={proc.returncode}\n"
            f"  stdout:\n{proc.stdout}\n"
            f"  stderr:\n{proc.stderr}\n"
        )
    return proc


def write_session_log(codex_home: Path, session_id: str, total_tokens: int) -> Path:
    sessions_dir = codex_home / "sessions" / "2026" / "02" / "16"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    log_path = sessions_dir / f"rollout-2026-02-16T10-00-00-{session_id}.jsonl"
    lines = [
        {"timestamp": "2026-02-16T10:00:00.000Z", "type": "turn_context", "payload": {"model": "gpt-5.3-codex"}},
        {
            "timestamp": "2026-02-16T10:00:03.000Z",
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
                    "last_token_usage": {"total_tokens": 234},
                    "model_context_window": 258400,
                },
                "rate_limits": {
                    "limit_id": "codex_bengalfox",
                    "limit_name": "GPT-5.3-Codex-Spark",
                    "plan_type": "pro",
                    "credits": {"has_credits": False, "unlimited": False, "balance": None},
                },
            },
        },
    ]
    log_path.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    return log_path


def main() -> None:
    tmp = tempfile.TemporaryDirectory(prefix="theworkshop-dashboard-cost-")
    root = Path(tmp.name).resolve()
    project_root = root / "project"
    codex_home = root / "codex_home"
    (project_root / "logs").mkdir(parents=True, exist_ok=True)
    (project_root / "outputs").mkdir(parents=True, exist_ok=True)
    (project_root / "workstreams").mkdir(parents=True, exist_ok=True)

    plan_text = """---
schema: theworkshop.plan.v1
kind: project
id: PJ-20260216-999
title: "Dashboard Cost Test"
status: in_progress
agreement_status: agreed
agreed_at: "2026-02-16T00:00:00Z"
agreed_notes: "dashboard cost test"
started_at: "2026-02-16T00:00:00Z"
updated_at: "2026-02-16T00:00:00Z"
completed_at: ""
completion_promise: PJ-20260216-999-DONE
---

# Goal

Test dashboard token/cost panels.
"""
    (project_root / "plan.md").write_text(plan_text, encoding="utf-8")

    session_id = "019c58b3-aab3-7c53-aa4e-f4ec9dc63c03"
    write_session_log(codex_home, session_id, total_tokens=5000)

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

    exec_entries = [
        {"duration_sec": 3, "work_item_id": "WI-COST-001"},
        {"duration_sec": 2, "work_item_id": "WI-COST-001"},
        {"duration_sec": 1, "work_item_id": "WI-COST-002"},
    ]
    (project_root / "logs" / "execution.jsonl").write_text(
        "\n".join(json.dumps(x) for x in exec_entries) + "\n",
        encoding="utf-8",
    )

    env = dict(os.environ)
    env["CODEX_HOME"] = str(codex_home)
    env["CODEX_THREAD_ID"] = session_id
    env["PATH"] = ""

    run([sys.executable, str(SCRIPTS_DIR / "dashboard_build.py"), "--project", str(project_root)], env=env)

    payload = json.loads((project_root / "outputs" / "dashboard.json").read_text(encoding="utf-8"))
    tokens = payload.get("tokens") or {}
    if str(tokens.get("cost_source") or "") != "estimated_from_rates":
        raise RuntimeError(f"Expected cost_source=estimated_from_rates, got {tokens.get('cost_source')!r}")
    if str(tokens.get("billing_mode") or "") != "subscription_auth":
        raise RuntimeError(f"Expected billing_mode=subscription_auth, got {tokens.get('billing_mode')!r}")
    billed_session = tokens.get("billed_session_cost_usd")
    if billed_session is None or float(billed_session) != 0.0:
        raise RuntimeError(f"Expected billed_session_cost_usd=0.0, got {billed_session!r}")
    if float(tokens.get("estimated_project_cost_usd") or 0.0) <= 0.0:
        raise RuntimeError(f"Expected estimated_project_cost_usd > 0, got {tokens.get('estimated_project_cost_usd')!r}")
    by_wi = tokens.get("by_work_item") or []
    if not by_wi:
        raise RuntimeError("Expected by_work_item entries in dashboard tokens payload")

    html = (project_root / "outputs" / "dashboard.html").read_text(encoding="utf-8", errors="ignore")
    for marker in (
        "Session Cost",
        "Project Cost (Delta)",
        "API-Equivalent Spend By Work Item (Estimated)",
        "$0.0000 billed",
        "plan: Codex auth/subscription",
        "WI-COST-001",
    ):
        if marker not in html:
            raise RuntimeError(f"Expected subscription dashboard.html to contain {marker!r}")

    # Force metered branch via override and verify table title/plan label switch.
    env_metered = dict(env)
    env_metered["THEWORKSHOP_BILLING_MODE"] = "metered_api"
    run([sys.executable, str(SCRIPTS_DIR / "dashboard_build.py"), "--project", str(project_root)], env=env_metered)

    payload_metered = json.loads((project_root / "outputs" / "dashboard.json").read_text(encoding="utf-8"))
    tokens_metered = payload_metered.get("tokens") or {}
    if str(tokens_metered.get("billing_mode") or "") != "metered_api":
        raise RuntimeError(f"Expected metered override, got {tokens_metered.get('billing_mode')!r}")

    html_metered = (project_root / "outputs" / "dashboard.html").read_text(encoding="utf-8", errors="ignore")
    for marker in ("Spend By Work Item (Estimated)", "plan: metered API", "WI-COST-001"):
        if marker not in html_metered:
            raise RuntimeError(f"Expected metered dashboard.html to contain {marker!r}")

    print("DASHBOARD COST PANEL TEST PASSED")
    print(str(project_root))
    tmp.cleanup()


if __name__ == "__main__":
    main()
