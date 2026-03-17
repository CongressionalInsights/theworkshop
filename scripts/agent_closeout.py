#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from tw_tools import run_script
from twlib import now_iso, resolve_project_root


TERMINAL_STATUSES = ("completed", "failed", "blocked", "stopped")


def _parse_json_output(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw or "{}")
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _run_curator(project_root: Path, script_name: str, *, work_item_id: str, agent_id: str) -> tuple[dict[str, Any], list[str]]:
    result = run_script(
        script_name,
        [
            "--project",
            str(project_root),
            "--work-item-id",
            work_item_id,
            "--agent-id",
            agent_id,
            "--write",
        ],
        check=False,
    )
    if result.returncode == 0:
        return _parse_json_output(result.stdout), []
    error = f"{script_name} failed exit={result.returncode}"
    if result.stderr.strip():
        error += f": {result.stderr.strip()}"
    return {}, [error]


def main() -> None:
    parser = argparse.ArgumentParser(description="Close out a manual/external subagent run and promote staged learning once.")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--agent-id", required=True, help="Logical agent-run identifier")
    parser.add_argument("--work-item-id", required=True, help="Related WI-... identifier")
    parser.add_argument("--status", required=True, choices=TERMINAL_STATUSES, help="Terminal status for the agent run")
    parser.add_argument("--source", default="manual", choices=["manual", "external"], help="Telemetry source classification")
    parser.add_argument("--agent-type", default="", help="Agent type (for example: worker, explorer)")
    parser.add_argument("--runtime-agent-name", default="", help="Resolved runtime agent name when known")
    parser.add_argument("--agent-profile", default="", help="Resolved planning profile when known")
    parser.add_argument("--message", default="", help="Optional free-form terminal summary")
    parser.add_argument("--duration-sec", type=float, default=0.0, help="Optional agent-run duration in seconds")
    parser.add_argument("--no-dashboard", action="store_true", help="Skip best-effort dashboard rebuild")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    agent_id = args.agent_id.strip()
    work_item_id = args.work_item_id.strip()
    status = args.status.strip()

    memory_summary, memory_errors = _run_curator(
        project_root,
        "memory_curate.py",
        work_item_id=work_item_id,
        agent_id=agent_id,
    )
    lessons_summary, lesson_errors = _run_curator(
        project_root,
        "lessons_curate.py",
        work_item_id=work_item_id,
        agent_id=agent_id,
    )
    learning_errors = memory_errors + lesson_errors

    meta_payload: dict[str, Any] = {
        "closeout_type": "manual_subagent",
        "closed_at": now_iso(),
        "memory_candidate_count": int(memory_summary.get("candidate_count") or 0),
        "memory_promoted_count": int(memory_summary.get("promoted_count") or 0),
        "lesson_candidate_count": int(lessons_summary.get("candidate_count") or 0),
        "lesson_promoted_count": int(lessons_summary.get("promoted_count") or 0),
        "learning_errors": learning_errors,
    }
    if args.runtime_agent_name.strip():
        meta_payload["runtime_agent_name"] = args.runtime_agent_name.strip()
    if args.agent_profile.strip():
        meta_payload["agent_profile"] = args.agent_profile.strip()

    message = args.message.strip() or f"agent closeout: {status}"
    log_result = run_script(
        "agent_log.py",
        [
            "--project",
            str(project_root),
            "--event",
            status,
            "--agent-id",
            agent_id,
            "--agent-type",
            args.agent_type.strip(),
            "--work-item-id",
            work_item_id,
            "--status",
            status,
            "--message",
            message,
            "--duration-sec",
            str(float(args.duration_sec or 0.0)),
            "--source",
            args.source.strip(),
            "--meta-json",
            json.dumps(meta_payload, separators=(",", ":")),
            "--no-dashboard",
        ],
        check=True,
    )

    dashboard_error = ""
    if not args.no_dashboard:
        dashboard_result = run_script(
            "dashboard_projector.py",
            ["--project", str(project_root)],
            check=False,
        )
        if dashboard_result.returncode != 0:
            dashboard_error = dashboard_result.stderr.strip() or f"dashboard_projector.py failed exit={dashboard_result.returncode}"
            print(f"warning: {dashboard_error}", file=sys.stderr)

    payload = {
        "schema": "theworkshop.agent-closeout.v1",
        "generated_at": now_iso(),
        "project": str(project_root),
        "agent_id": agent_id,
        "work_item_id": work_item_id,
        "status": status,
        "source": args.source.strip(),
        "agent_type": args.agent_type.strip(),
        "runtime_agent_name": args.runtime_agent_name.strip(),
        "agent_profile": args.agent_profile.strip(),
        "event_log_path": log_result.stdout.strip(),
        "memory": memory_summary,
        "lessons": lessons_summary,
        "learning_errors": learning_errors,
        "dashboard_error": dashboard_error,
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
