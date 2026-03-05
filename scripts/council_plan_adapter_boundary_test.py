#!/usr/bin/env python3
from __future__ import annotations

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
    merged["THEWORKSHOP_NO_OPEN"] = "1"
    merged["THEWORKSHOP_NO_MONITOR"] = "1"
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
    with tempfile.TemporaryDirectory(prefix="theworkshop-council-adapter-") as td:
        base = Path(td).resolve()
        project_root = Path(
            run(py("project_new.py") + ["--name", "Council Adapter Boundary", "--base-dir", str(base)]).stdout.strip()
        ).resolve()

        env_missing_gemini = {"PATH": ""}
        proc_fail = run(py("council_plan.py") + ["--project", str(project_root)], env=env_missing_gemini, check=False)
        if proc_fail.returncode == 0:
            raise RuntimeError("Expected council_plan to fail when gemini adapter is unavailable and not in dry-run mode")
        combined = (proc_fail.stdout or "") + (proc_fail.stderr or "")
        if "optional planner adapter unavailable: Gemini CLI not installed or not on PATH" not in combined:
            raise RuntimeError(f"Expected optional adapter guidance, got:\n{combined}")

        proc_dry = run(py("council_plan.py") + ["--project", str(project_root), "--dry-run"], env=env_missing_gemini)
        if proc_dry.returncode != 0:
            raise RuntimeError(f"Expected dry-run council plan to pass without planner adapters, got:\n{proc_dry.stdout}\n{proc_dry.stderr}")

        print("COUNCIL PLAN ADAPTER BOUNDARY TEST PASSED")


if __name__ == "__main__":
    main()
