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
    with tempfile.TemporaryDirectory(prefix="theworkshop-dashboard-ui-") as td:
        base_dir = Path(td).resolve()
        project_root = Path(
            run(py("project_new.py") + ["--name", "Dashboard UI Interaction Test", "--base-dir", str(base_dir)]).stdout.strip()
        ).resolve()
        ws_id = run(py("workstream_add.py") + ["--project", str(project_root), "--title", "Main Workstream"]).stdout.strip()
        wi_1 = run(
            py("job_add.py")
            + [
                "--project",
                str(project_root),
                "--workstream",
                ws_id,
                "--title",
                "Single job for UI test",
            ]
        ).stdout.strip()

        logs_dir = project_root / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        with (logs_dir / "agents.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "timestamp": "2026-02-16T00:00:00Z",
                        "agent_id": "019c9f40-8d1f-7e62-bd00-90dc0e097c6a",
                        "work_item_id": wi_1,
                        "event": "completed",
                        "status": "completed",
                        "message": "UI marker seed event",
                        "source": "manual",
                    }
                )
                + "\n"
            )

        run(py("dashboard_build.py") + ["--project", str(project_root)])

        html_path = project_root / "outputs" / "dashboard.html"
        html = html_path.read_text(encoding="utf-8", errors="ignore")

        required_markers = [
            "TheWorkshop Dashboard",
            "id=\"twQuery\"",
            "id=\"twFocusAll\"",
            "id=\"twFocusAtRisk\"",
            "id=\"twFocusActive\"",
            "id=\"twFocusBlocked\"",
            "id=\"twFocusDone\"",
            "id=\"twStatusFilters\"",
            "id=\"twTruthFilters\"",
            "id=\"twQueueTable\"",
            "data-ws-card='1'",
            "data-wi-row='1'",
            "data-event-row='1'",
            "data-event-summary='1'",
            "data-event-details='1'",
            "data-event-raw='1'",
            "Session Cost",
            "Project Cost (Delta)",
            "Sub-Agents",
        ]
        for marker in required_markers:
            if marker not in html:
                raise RuntimeError(f"Expected dashboard.html to contain marker {marker!r}")

        print("DASHBOARD UI INTERACTION TEST PASSED")
        print(str(project_root))


if __name__ == "__main__":
    main()
