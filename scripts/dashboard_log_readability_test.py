#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
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
    with tempfile.TemporaryDirectory(prefix="theworkshop-dashboard-log-readability-") as td:
        base_dir = Path(td).resolve()
        project_root = Path(
            run(py("project_new.py") + ["--name", "Dashboard Log Readability Test", "--base-dir", str(base_dir)]).stdout.strip()
        ).resolve()
        ws_id = run(py("workstream_add.py") + ["--project", str(project_root), "--title", "Main Workstream"]).stdout.strip()
        wi = run(
            py("job_add.py")
            + [
                "--project",
                str(project_root),
                "--workstream",
                ws_id,
                "--title",
                "Readable job",
            ]
        ).stdout.strip()

        uuid_full = "019c9f40-8d1f-7e62-bd00-90dc0e097c6a"
        logs_dir = project_root / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        with (logs_dir / "agents.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "timestamp": "2026-02-16T00:00:00Z",
                        "agent_id": uuid_full,
                        "agent_type": "worker",
                        "work_item_id": wi,
                        "event": "active",
                        "status": "active",
                        "message": "active active delegated and started",
                        "source": "manual",
                    }
                )
                + "\n"
            )
            fh.write(
                json.dumps(
                    {
                        "timestamp": "2026-02-16T00:01:00Z",
                        "agent_id": uuid_full,
                        "agent_type": "worker",
                        "work_item_id": wi,
                        "event": "completed",
                        "status": "completed",
                        "message": "completed completed output verified",
                        "source": "manual",
                    }
                )
                + "\n"
            )

        run(py("dashboard_build.py") + ["--project", str(project_root)])

        payload = json.loads((project_root / "outputs" / "dashboard.json").read_text(encoding="utf-8"))
        html = (project_root / "outputs" / "dashboard.html").read_text(encoding="utf-8", errors="ignore")

        recent = (payload.get("subagents") or {}).get("recent_events") or []
        if not recent:
            raise RuntimeError("Expected normalized recent sub-agent events in payload")
        first = recent[-1]
        if not str(first.get("display_text") or "").strip():
            raise RuntimeError(f"Missing display_text in normalized event: {first}")
        if not str(first.get("display_work_item") or "").startswith("Readable job (WI-"):
            raise RuntimeError(f"Expected title-first display_work_item, got: {first.get('display_work_item')!r}")
        if "raw" not in first or not isinstance(first.get("raw"), dict):
            raise RuntimeError(f"Expected raw event payload preserved, got: {first}")

        if "data-event-row='1'" not in html or "data-event-details='1'" not in html or "data-event-raw='1'" not in html:
            raise RuntimeError("Expected event row/details/raw anchors in dashboard HTML")
        if "Readable job (WI-" not in html:
            raise RuntimeError("Expected title-first humanized event text in dashboard HTML")
        html_no_raw = re.sub(r"<pre class='mono' data-event-raw='1'>.*?</pre>", "", html, flags=re.DOTALL)
        if "active active" in html_no_raw or "completed completed" in html_no_raw:
            raise RuntimeError("Expected duplicate status words to be normalized out of visible dashboard text")

        if uuid_full not in html:
            raise RuntimeError("Expected full UUID to remain available in raw details block")
        if uuid_full in html_no_raw:
            raise RuntimeError("Expected full UUID to be hidden from visible rows and only present in raw details")

        print("DASHBOARD LOG READABILITY TEST PASSED")
        print(str(project_root))


if __name__ == "__main__":
    main()
