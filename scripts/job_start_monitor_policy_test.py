#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from twlib import now_iso  # noqa: E402
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


def read_policy(project_root: Path) -> str:
    doc = split_frontmatter((project_root / "plan.md").read_text(encoding="utf-8", errors="ignore"))
    return str(doc.frontmatter.get("monitor_open_policy") or "").strip()


def make_ready_project(base_dir: Path, *, name: str) -> tuple[Path, str]:
    project_root = Path(run(py("project_new.py") + ["--name", name, "--base-dir", str(base_dir)]).stdout.strip()).resolve()
    ws_id = run(py("workstream_add.py") + ["--project", str(project_root), "--title", "WS"]).stdout.strip()
    wi = run(py("job_add.py") + ["--project", str(project_root), "--workstream", ws_id, "--title", "Job"]).stdout.strip()
    set_frontmatter(
        project_root / "plan.md",
        agreement_status="agreed",
        agreed_at=now_iso(),
        agreed_notes="monitor policy test",
        status="in_progress",
        updated_at=now_iso(),
    )
    return project_root, wi


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="theworkshop-job-start-policy-") as td:
        base_dir = Path(td).resolve()

        project1, wi1 = make_ready_project(base_dir, name="No Open Is Ephemeral")
        if read_policy(project1) != "once":
            raise RuntimeError("Expected new project monitor_open_policy=once")
        run(py("job_start.py") + ["--project", str(project1), "--work-item-id", wi1, "--no-open"])
        if read_policy(project1) != "once":
            raise RuntimeError("Expected --no-open to keep monitor_open_policy=once")

        project2, wi2 = make_ready_project(base_dir, name="Manual Policy Override")
        run(
            py("job_start.py")
            + ["--project", str(project2), "--work-item-id", wi2, "--monitor-policy", "manual", "--no-open"]
        )
        if read_policy(project2) != "manual":
            raise RuntimeError("Expected --monitor-policy manual to persist monitor_open_policy=manual")

        print("JOB START MONITOR POLICY TEST PASSED")


if __name__ == "__main__":
    main()
