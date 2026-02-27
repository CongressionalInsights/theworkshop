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
    for k, v in updates.items():
        doc.frontmatter[k] = v
    path.write_text(join_frontmatter(doc), encoding="utf-8")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="theworkshop-transition-done-") as td:
        base = Path(td).resolve()
        project_root = Path(run(py("project_new.py") + ["--name", "Transition Done Guard", "--base-dir", str(base)]).stdout.strip())
        ws_id = run(py("workstream_add.py") + ["--project", str(project_root), "--title", "WS"] ).stdout.strip()
        _wi = run(py("job_add.py") + ["--project", str(project_root), "--workstream", ws_id, "--title", "Job"]).stdout.strip()

        set_frontmatter(project_root / "plan.md", agreement_status="agreed", agreed_at=now_iso(), agreed_notes="test", status="in_progress")

        ws_fail = run(
            py("transition.py")
            + [
                "--project",
                str(project_root),
                "--entity-kind",
                "workstream",
                "--entity-id",
                ws_id,
                "--to-status",
                "done",
                "--reason",
                "should fail",
            ],
            check=False,
        )
        if ws_fail.returncode == 0:
            raise RuntimeError("Expected workstream done transition to fail when jobs are not done")

        pj_fail = run(
            py("transition.py")
            + [
                "--project",
                str(project_root),
                "--entity-kind",
                "project",
                "--to-status",
                "done",
                "--reason",
                "should fail",
            ],
            check=False,
        )
        if pj_fail.returncode == 0:
            raise RuntimeError("Expected project done transition to fail when workstreams are not done")

        print("TRANSITION DONE GUARD TEST PASSED")


if __name__ == "__main__":
    main()
