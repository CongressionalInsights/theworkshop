#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from twyaml import join_frontmatter, split_frontmatter  # noqa: E402


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


def set_frontmatter(path: Path, **updates) -> None:
    doc = split_frontmatter(path.read_text(encoding="utf-8", errors="ignore"))
    for key, value in updates.items():
        doc.frontmatter[key] = value
    path.write_text(join_frontmatter(doc), encoding="utf-8")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="theworkshop-agent-profile-") as td:
        base = Path(td).resolve()
        project_root = Path(
            run(py("project_new.py") + ["--name", "Agent Profile Test", "--base-dir", str(base)]).stdout.strip()
        ).resolve()
        ws_id = run(py("workstream_add.py") + ["--project", str(project_root), "--title", "Role WS"]).stdout.strip()
        wi = run(
            py("job_add.py")
            + [
                "--project",
                str(project_root),
                "--workstream",
                ws_id,
                "--title",
                "Role job",
                "--stakes",
                "critical",
            ]
        ).stdout.strip()

        job_plan = next(project_root.glob("workstreams/WS-*/jobs/WI-*/plan.md"))
        set_frontmatter(job_plan, orchestration_mode="review")

        proc = run(
            py("resolve_agent_profile.py")
            + [
                "--project",
                str(project_root),
                "--work-item-id",
                wi,
                "--write",
            ]
        )
        payload = json.loads(proc.stdout)

        if payload.get("resolved_profile") != "reviewer":
            raise RuntimeError(f"Expected reviewer profile, got: {payload}")

        doc = split_frontmatter(job_plan.read_text(encoding="utf-8", errors="ignore"))
        if str(doc.frontmatter.get("agent_profile") or "") != "reviewer":
            raise RuntimeError("Expected agent_profile to be written to job frontmatter")

        out_path = job_plan.parent / "artifacts" / "agent-profile.json"
        if not out_path.exists():
            raise RuntimeError(f"Expected artifact not found: {out_path}")

        print("RESOLVE AGENT PROFILE TEST PASSED")


if __name__ == "__main__":
    main()
