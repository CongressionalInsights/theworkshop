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
    with tempfile.TemporaryDirectory(prefix="theworkshop-quick-runtime-") as td:
        base_dir = Path(td).resolve()
        project_root = Path(
            run(py("project_new.py") + ["--name", "Quick Runtime Test", "--base-dir", str(base_dir)]).stdout.strip()
        ).resolve()

        run(
            py("quick.py")
            + [
                "--project",
                str(project_root),
                "--title",
                "Quick runtime path",
                "--command",
                "printf quick-runtime-test",
            ],
            env={"THEWORKSHOP_NO_OPEN": "1"},
        )

        runtime_state = project_root / "tmp" / "monitor-runtime.json"
        if not runtime_state.exists():
            raise RuntimeError("Expected quick.py to route through monitor_runtime.py")

        payload = json.loads(runtime_state.read_text(encoding="utf-8"))
        if str(payload.get("source") or "") not in {"monitor_runtime.start", "monitor_runtime.status"}:
            raise RuntimeError(f"Unexpected runtime source after quick.py: {payload}")

        if (project_root / "tmp" / "dashboard-open.json").exists():
            raise RuntimeError("quick.py should not create legacy dashboard-open.json anymore")

    print("QUICK MONITOR RUNTIME TEST PASSED")


if __name__ == "__main__":
    main()
