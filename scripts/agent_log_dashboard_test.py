#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent


def py(script: str) -> list[str]:
    return [sys.executable, str(SCRIPTS_DIR / script)]


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["THEWORKSHOP_NO_OPEN"] = "1"
    env["THEWORKSHOP_NO_MONITOR"] = "1"
    env["THEWORKSHOP_NO_KEYCHAIN"] = "1"
    proc = subprocess.run(cmd, text=True, capture_output=True, env=env)
    if check and proc.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            f"  cmd={' '.join(cmd)}\n"
            f"  exit={proc.returncode}\n"
            f"  stdout:\n{proc.stdout}\n"
            f"  stderr:\n{proc.stderr}\n"
        )
    return proc


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="theworkshop-agent-log-dashboard-") as td:
        base_dir = Path(td).resolve()
        project_root = Path(
            run(py("project_new.py") + ["--name", "Agent Log Dashboard Test", "--base-dir", str(base_dir)]).stdout.strip()
        ).resolve()
        ws_id = run(py("workstream_add.py") + ["--project", str(project_root), "--title", "Main Workstream"]).stdout.strip()
        run(
            py("job_add.py")
            + [
                "--project",
                str(project_root),
                "--workstream",
                ws_id,
                "--title",
                "Single job",
            ]
        )

        logs_dir = project_root / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        events = [
            {
                "timestamp": "2026-02-16T00:00:00Z",
                "agent_id": "agent-a",
                "work_item_id": "WI-TEST-A",
                "event": "started",
                "status": "active",
                "message": "Picked up delegated work.",
            },
            {
                "timestamp": "2026-02-16T00:01:00Z",
                "agent_id": "agent-b",
                "work_item_id": "WI-TEST-B",
                "event": "completed",
                "status": "completed",
                "message": "Completed delegated work.",
            },
            {
                "timestamp": "2026-02-16T00:02:00Z",
                "agent_id": "agent-c",
                "work_item_id": "WI-TEST-C",
                "event": "failed",
                "status": "failed",
                "message": "TruthGate checks failed.",
            },
        ]
        with (logs_dir / "agents.jsonl").open("a", encoding="utf-8") as fh:
            for evt in events:
                fh.write(json.dumps(evt) + "\n")

        run(py("dashboard_build.py") + ["--project", str(project_root)])

        payload_path = project_root / "outputs" / "dashboard.json"
        html_path = project_root / "outputs" / "dashboard.html"
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        html = html_path.read_text(encoding="utf-8", errors="ignore")

        subagents = payload.get("subagents") or {}
        counts = subagents.get("counts") or {}
        if int(counts.get("active") or 0) != 1:
            raise RuntimeError(f"Expected active=1 in subagent counts, got {counts}")
        if int(counts.get("completed") or 0) != 1:
            raise RuntimeError(f"Expected completed=1 in subagent counts, got {counts}")
        if int(counts.get("failed") or 0) != 1:
            raise RuntimeError(f"Expected failed=1 in subagent counts, got {counts}")

        recent_events = subagents.get("recent_events") or []
        if len(recent_events) < 3:
            raise RuntimeError(f"Expected at least 3 recent subagent events, got {len(recent_events)}")

        if "Sub-Agents" not in html:
            raise RuntimeError("Expected dashboard HTML to include the Sub-Agents panel marker text.")

        print("AGENT LOG DASHBOARD TEST PASSED")
        print(str(project_root))


if __name__ == "__main__":
    main()
