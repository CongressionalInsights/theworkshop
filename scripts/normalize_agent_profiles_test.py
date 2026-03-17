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
    with tempfile.TemporaryDirectory(prefix="theworkshop-normalize-agent-profiles-") as td:
        base = Path(td).resolve()
        project_root = Path(
            run(py("project_new.py") + ["--name", "Normalize Agent Profiles Test", "--base-dir", str(base)]).stdout.strip()
        ).resolve()
        ws_id = run(py("workstream_add.py") + ["--project", str(project_root), "--title", "Role WS"]).stdout.strip()
        run(
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
        )

        job_plan = next(project_root.glob("workstreams/WS-*/jobs/WI-*/plan.md"))
        set_frontmatter(job_plan, agent_profile="reviewer", agent_type_hint="worker")

        dry_run = json.loads(run(py("normalize_agent_profiles.py") + ["--project", str(project_root)]).stdout)
        if len(dry_run.get("changes") or []) != 1:
            raise RuntimeError(f"Expected exactly one dry-run change, got: {dry_run}")
        change = dry_run["changes"][0]
        if change.get("after_agent_profile") != "theworkshop_reviewer":
            raise RuntimeError(f"Expected canonical reviewer profile in dry-run, got: {dry_run}")

        run(py("normalize_agent_profiles.py") + ["--project", str(project_root), "--write"])
        doc = split_frontmatter(job_plan.read_text(encoding="utf-8", errors="ignore"))
        if str(doc.frontmatter.get("agent_profile") or "") != "theworkshop_reviewer":
            raise RuntimeError("Expected canonical agent_profile after normalization")
        if "agent_type_hint" in doc.frontmatter:
            raise RuntimeError("Expected agent_type_hint to be removed by normalization")

        print("NORMALIZE AGENT PROFILES TEST PASSED")


if __name__ == "__main__":
    main()
