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


def read_frontmatter(path: Path) -> dict:
    return split_frontmatter(path.read_text(encoding="utf-8", errors="ignore")).frontmatter


def find_job_plan(project_root: Path, wi: str) -> Path:
    matches = list(project_root.glob(f"workstreams/WS-*/jobs/{wi}-*/plan.md"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one job plan for {wi}, got {len(matches)}")
    return matches[0]


def main() -> None:
    tmp = tempfile.TemporaryDirectory(prefix="theworkshop-dep-gate-")
    base_dir = Path(tmp.name).resolve()

    proj = run(py("project_new.py") + ["--name", "Dependency Gate Test", "--base-dir", str(base_dir)]).stdout.strip()
    project_root = Path(proj).resolve()
    ws = run(py("workstream_add.py") + ["--project", str(project_root), "--title", "WS"]).stdout.strip()
    wi1 = run(py("job_add.py") + ["--project", str(project_root), "--workstream", ws, "--title", "First", "--stakes", "low"]).stdout.strip()
    wi2 = run(
        py("job_add.py")
        + ["--project", str(project_root), "--workstream", ws, "--title", "Second", "--stakes", "low", "--depends-on", wi1]
    ).stdout.strip()

    set_frontmatter(
        project_root / "plan.md",
        agreement_status="agreed",
        agreed_at=now_iso(),
        agreed_notes="dependency gate test",
        updated_at=now_iso(),
    )

    blocked = run(py("job_start.py") + ["--project", str(project_root), "--work-item-id", wi2], check=False)
    if blocked.returncode == 0:
        raise RuntimeError("Expected dependency gate to block job_start when dependency is not done")
    if "dependencies are not done" not in (blocked.stderr + blocked.stdout):
        raise RuntimeError("Expected dependency error message when dependency is not done")

    no_note = run(
        py("job_start.py") + ["--project", str(project_root), "--work-item-id", wi2, "--allow-unmet-deps"],
        check=False,
    )
    if no_note.returncode == 0:
        raise RuntimeError("Expected --allow-unmet-deps without --decision-note to fail")
    if "requires --decision-note" not in (no_note.stderr + no_note.stdout):
        raise RuntimeError("Expected explicit decision-note requirement message")

    decision_note = "Urgent override for dependency gate test"
    run(
        py("job_start.py")
        + [
            "--project",
            str(project_root),
            "--work-item-id",
            wi2,
            "--allow-unmet-deps",
            "--decision-note",
            decision_note,
        ]
    )

    proj_text = (project_root / "plan.md").read_text(encoding="utf-8", errors="ignore")
    if decision_note not in proj_text:
        raise RuntimeError("Expected project Decisions log to include dependency override note")

    wi2_status = str(read_frontmatter(find_job_plan(project_root, wi2)).get("status") or "")
    if wi2_status != "in_progress":
        raise RuntimeError(f"Expected {wi2} status=in_progress after override, got {wi2_status!r}")

    print("STATUS DEPENDENCY GATE TEST PASSED")
    print(str(project_root))
    tmp.cleanup()


if __name__ == "__main__":
    main()
