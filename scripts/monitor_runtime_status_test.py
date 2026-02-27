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


def run(cmd: list[str], *, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    merged = dict(os.environ)
    merged["THEWORKSHOP_NO_KEYCHAIN"] = "1"
    if env:
        merged.update(env)
    proc = subprocess.run(cmd, text=True, capture_output=True, env=merged)
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
    with tempfile.TemporaryDirectory(prefix="theworkshop-monitor-runtime-") as td:
        base_dir = Path(td).resolve()
        project_root = Path(
            run(py("project_new.py") + ["--name", "Monitor Runtime Status Test", "--base-dir", str(base_dir)]).stdout.strip()
        ).resolve()

        disabled = run(
            py("monitor_runtime.py") + ["start", "--project", str(project_root)],
            env={"THEWORKSHOP_NO_OPEN": "1", "THEWORKSHOP_NO_MONITOR": "1"},
        )
        disabled_payload = json.loads(disabled.stdout)
        if str(disabled_payload.get("status") or "") != "disabled":
            raise RuntimeError(f"Expected status=disabled, got: {disabled_payload}")

        idle = run(
            py("monitor_runtime.py") + ["start", "--project", str(project_root), "--no-open", "--no-watch"],
            env={"THEWORKSHOP_NO_OPEN": "0", "THEWORKSHOP_NO_MONITOR": "0"},
        )
        idle_payload = json.loads(idle.stdout)
        if str(idle_payload.get("status") or "") != "idle":
            raise RuntimeError(f"Expected status=idle, got: {idle_payload}")
        if bool(idle_payload.get("watch_alive")):
            raise RuntimeError(f"Expected watch_alive=false for idle status, got: {idle_payload}")

        print("MONITOR RUNTIME STATUS TEST PASSED")
        print(str(project_root))


if __name__ == "__main__":
    main()

