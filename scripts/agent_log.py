#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from twlib import now_iso, resolve_project_root


def main() -> None:
    parser = argparse.ArgumentParser(description="Append an agent event line to logs/agents.jsonl.")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--event", required=True, help="Event type")
    parser.add_argument("--agent-id", required=True, help="Agent identifier")
    parser.add_argument("--agent-type", default="", help="Agent type (for example: codex, subagent)")
    parser.add_argument("--work-item-id", default="", help="Related WI-... identifier")
    parser.add_argument("--status", default="", help="Event status")
    parser.add_argument("--message", default="", help="Free-form message")
    parser.add_argument("--duration-sec", type=float, default=0.0, help="Event duration in seconds")
    parser.add_argument("--timestamp", default="", help="Override timestamp (ISO-8601; default now)")
    parser.add_argument("--out", help="Log file path (default: logs/agents.jsonl)")
    parser.add_argument("--no-dashboard", action="store_true", help="Skip best-effort dashboard rebuild")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    default_out = project_root / "logs" / "agents.jsonl"
    out_path = Path(args.out).expanduser().resolve() if args.out else default_out
    out_path.parent.mkdir(parents=True, exist_ok=True)

    ts = args.timestamp.strip() or now_iso()
    payload = {
        "timestamp": ts,
        "event": args.event.strip(),
        "agent_id": args.agent_id.strip(),
        "agent_type": args.agent_type.strip(),
        "work_item_id": args.work_item_id.strip(),
        "status": args.status.strip(),
        "message": args.message.strip(),
        "duration_sec": float(args.duration_sec),
    }

    with out_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, separators=(",", ":")) + "\n")

    if not args.no_dashboard:
        scripts_dir = Path(__file__).resolve().parent
        proc = subprocess.run(
            [sys.executable, str(scripts_dir / "dashboard_build.py"), "--project", str(project_root)],
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            print("warning: dashboard_build.py failed after agent-log append", file=sys.stderr)
            if proc.stderr:
                print(proc.stderr, end="", file=sys.stderr)

    print(str(out_path))


if __name__ == "__main__":
    main()
