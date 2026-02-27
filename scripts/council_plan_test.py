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
    with tempfile.TemporaryDirectory(prefix="theworkshop-council-") as td:
        base = Path(td).resolve()
        project_root = Path(
            run(py("project_new.py") + ["--name", "Council Test", "--base-dir", str(base)]).stdout.strip()
        ).resolve()

        run(py("council_plan.py") + ["--project", str(project_root), "--dry-run"])

        out_dir = project_root / "outputs" / "council"
        plan_json = out_dir / "council-plan.json"
        final_md = out_dir / "final-plan.md"
        if not plan_json.exists() or not final_md.exists():
            raise RuntimeError("Expected council artifacts missing")

        payload = json.loads(plan_json.read_text(encoding="utf-8"))
        if payload.get("schema") != "theworkshop.council.v1":
            raise RuntimeError(f"Unexpected council schema: {payload.get('schema')}")
        planners = payload.get("planners") or []
        if len(planners) < 1:
            raise RuntimeError("Expected at least one planner result")

        md = final_md.read_text(encoding="utf-8", errors="ignore")
        if "Council" not in md and "Draft" not in md:
            raise RuntimeError("final-plan.md did not contain expected draft content")

        print("COUNCIL PLAN TEST PASSED")


if __name__ == "__main__":
    main()
