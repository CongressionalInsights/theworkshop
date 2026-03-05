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
    with tempfile.TemporaryDirectory(prefix="theworkshop-terminal-cleanup-") as td:
        base_dir = Path(td).resolve()
        project_root = Path(
            run(py("project_new.py") + ["--name", "Terminal Cleanup Test", "--base-dir", str(base_dir)]).stdout.strip()
        ).resolve()

        start = run(py("monitor_runtime.py") + ["start", "--project", str(project_root), "--no-open"])
        start_payload = json.loads(start.stdout)
        if not bool(start_payload.get("watch_alive")):
            raise RuntimeError(f"Expected watcher to be alive after monitor start: {start_payload}")
        if not bool(start_payload.get("server_alive")):
            raise RuntimeError(f"Expected server to be alive after monitor start: {start_payload}")

        run(
            py("project_close.py")
            + ["--project", str(project_root), "--status", "cancelled", "--reason", "terminal cleanup test"]
        )

        runtime_state = project_root / "tmp" / "monitor-runtime.json"
        if not runtime_state.exists():
            raise RuntimeError("Expected monitor-runtime.json cleanup snapshot to remain after close")

        payload = json.loads(runtime_state.read_text(encoding="utf-8"))
        if str(payload.get("status") or "") != "terminal":
            raise RuntimeError(f"Expected terminal runtime status after closeout: {payload}")
        if str(payload.get("cleanup_status") or "") != "pruned":
            raise RuntimeError(f"Expected cleanup_status=pruned after closeout: {payload}")

        for rel in (
            "tmp/dashboard-open.json",
            "tmp/dashboard-watch.json",
            "tmp/dashboard-watch.log",
            "tmp/dashboard-server.json",
            "tmp/dashboard-server.log",
            "tmp/workflow-runner.json",
            "tmp/workflow-runner.log",
            "tmp/dashboard-projector.lock",
        ):
            if (project_root / rel).exists():
                raise RuntimeError(f"Expected transient runtime artifact to be pruned: {rel}")

        for rel in ("outputs/dashboard.html", "outputs/dashboard.json"):
            if not (project_root / rel).exists():
                raise RuntimeError(f"Expected canonical dashboard artifact to remain: {rel}")

    print("TERMINAL CLEANUP TEST PASSED")


if __name__ == "__main__":
    main()
