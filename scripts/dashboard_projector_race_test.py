#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent


def py(script: str) -> list[str]:
    return [sys.executable, str(SCRIPTS_DIR / script)]


def run(cmd: list[str], *, env: dict | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
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
    with tempfile.TemporaryDirectory(prefix="theworkshop-projector-race-") as td:
        base = Path(td).resolve()
        project_root = Path(run(py("project_new.py") + ["--name", "Projector Race", "--base-dir", str(base)]).stdout.strip())

        cmds = [py("dashboard_projector.py") + ["--project", str(project_root)] for _ in range(8)]

        failures: list[str] = []
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(run, cmd, check=False) for cmd in cmds]
            for fut in as_completed(futures):
                proc = fut.result()
                if proc.returncode != 0:
                    failures.append((proc.stdout or "") + "\n" + (proc.stderr or ""))

        if failures:
            raise RuntimeError("Expected projector parallel runs to succeed; got failures:\n" + "\n---\n".join(failures))

        dashboard_json = project_root / "outputs" / "dashboard.json"
        payload = json.loads(dashboard_json.read_text(encoding="utf-8"))
        if payload.get("schema") != "theworkshop.dashboard.v1":
            raise RuntimeError("Invalid dashboard schema after race run")
        if int(payload.get("projection_seq") or 0) <= 0:
            raise RuntimeError("Expected projection_seq > 0")

        print("DASHBOARD PROJECTOR RACE TEST PASSED")


if __name__ == "__main__":
    main()
