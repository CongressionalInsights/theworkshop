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
    with tempfile.TemporaryDirectory(prefix="theworkshop-subagent-note-") as td:
        base_dir = Path(td).resolve()
        project_root = Path(
            run(py("project_new.py") + ["--name", "Subagent Telemetry Note Test", "--base-dir", str(base_dir)]).stdout.strip()
        ).resolve()
        ws_id = run(py("workstream_add.py") + ["--project", str(project_root), "--title", "Main"]).stdout.strip()
        run(py("job_add.py") + ["--project", str(project_root), "--workstream", ws_id, "--title", "Single Job"])

        run(py("dashboard_build.py") + ["--project", str(project_root)])
        payload = json.loads((project_root / "outputs" / "dashboard.json").read_text(encoding="utf-8"))
        html = (project_root / "outputs" / "dashboard.html").read_text(encoding="utf-8", errors="ignore")

        note = str((payload.get("subagents") or {}).get("telemetry_note") or "")
        if "No sub-agent telemetry found" not in note:
            raise RuntimeError(f"Expected missing telemetry note, got: {note!r}")
        if "No sub-agent telemetry found" not in html:
            raise RuntimeError("Expected telemetry note to be visible in dashboard HTML")
        dispatch0 = payload.get("dispatch") or {}
        if str(dispatch0.get("mode") or "") != "not_used":
            raise RuntimeError(f"Expected dispatch mode 'not_used' without telemetry, got: {dispatch0}")
        if "not used in this run" not in html:
            raise RuntimeError("Expected dashboard to show dispatch-not-used text when dispatch was not used.")

        dispatch_log = project_root / "logs" / "subagent-dispatch.jsonl"
        dispatch_log.parent.mkdir(parents=True, exist_ok=True)
        dispatch_log.write_text(
            "\n".join(
                [
                    json.dumps(
                        {
                            "timestamp": "2026-02-27T00:00:00Z",
                            "agent_id": "dispatch-a",
                            "work_item_id": "WI-TEST-1",
                            "event": "spawned",
                            "status": "active",
                            "message": "scheduled",
                        }
                    ),
                    json.dumps(
                        {
                            "timestamp": "2026-02-27T00:01:00Z",
                            "agent_id": "dispatch-b",
                            "work_item_id": "WI-TEST-2",
                            "event": "completed",
                            "status": "completed",
                            "message": "finished",
                        }
                    ),
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        run(py("dashboard_build.py") + ["--project", str(project_root)])
        payload2 = json.loads((project_root / "outputs" / "dashboard.json").read_text(encoding="utf-8"))
        subagents2 = payload2.get("subagents") or {}
        dispatch2 = payload2.get("dispatch") or {}
        note2 = str(subagents2.get("telemetry_note") or "")
        counts2 = subagents2.get("counts") or {}
        if "legacy dispatch log" not in note2:
            raise RuntimeError(f"Expected dispatch-derived telemetry note, got: {note2!r}")
        if int(counts2.get("active") or 0) != 1 or int(counts2.get("completed") or 0) != 1:
            raise RuntimeError(f"Expected active/completed counts from dispatch fallback, got: {counts2}")
        if str(dispatch2.get("mode") or "") != "legacy_fallback":
            raise RuntimeError(f"Expected dispatch mode 'legacy_fallback', got: {dispatch2}")
        if "legacy dispatch log" not in str(dispatch2.get("telemetry_note") or ""):
            raise RuntimeError(f"Expected legacy fallback telemetry note in dispatch payload, got: {dispatch2}")

        print("DASHBOARD SUBAGENT TELEMETRY NOTE TEST PASSED")
        print(str(project_root))


if __name__ == "__main__":
    main()
