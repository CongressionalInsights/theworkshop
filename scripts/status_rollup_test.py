#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Allow importing TheWorkshop helpers from the scripts directory.
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
    for k, v in updates.items():
        doc.frontmatter[k] = v
    path.write_text(join_frontmatter(doc), encoding="utf-8")


def read_status(path: Path) -> str:
    return str(split_frontmatter(path.read_text(encoding="utf-8", errors="ignore")).frontmatter.get("status") or "")


def main() -> None:
    tmp = tempfile.TemporaryDirectory(prefix="theworkshop-rollup-")
    base_dir = Path(tmp.name).resolve()

    proj = run(py("project_new.py") + ["--name", "Rollup Test", "--base-dir", str(base_dir)]).stdout.strip()
    project_root = Path(proj).resolve()
    ws_id = run(py("workstream_add.py") + ["--project", str(project_root), "--title", "Single WS"]).stdout.strip()
    wi_id = run(
        py("job_add.py") + ["--project", str(project_root), "--workstream", ws_id, "--title", "Single WI", "--stakes", "normal"]
    ).stdout.strip()

    set_frontmatter(
        project_root / "plan.md",
        agreement_status="agreed",
        agreed_at=now_iso(),
        agreed_notes="status rollup test",
        updated_at=now_iso(),
    )

    run(py("job_start.py") + ["--project", str(project_root), "--work-item-id", wi_id])

    ws_plan = next(project_root.glob("workstreams/WS-*/plan.md"))
    proj_plan = project_root / "plan.md"
    ws_status = read_status(ws_plan)
    proj_status = read_status(proj_plan)
    if ws_status != "in_progress":
        raise RuntimeError(f"Expected workstream status=in_progress after job start, got {ws_status!r}")
    if proj_status != "in_progress":
        raise RuntimeError(f"Expected project status=in_progress after job start, got {proj_status!r}")

    run(py("plan_check.py") + ["--project", str(project_root)])
    print("STATUS ROLLUP TEST PASSED")
    print(str(project_root))

    tmp.cleanup()


if __name__ == "__main__":
    main()
