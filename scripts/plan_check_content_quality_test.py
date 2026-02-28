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
    tmp = tempfile.TemporaryDirectory(prefix="theworkshop-content-quality-")
    base_dir = Path(tmp.name).resolve()

    project_root = Path(
        run(py("project_new.py") + ["--name", "Content Quality Test", "--base-dir", str(base_dir)]).stdout.strip()
    ).resolve()
    ws = run(py("workstream_add.py") + ["--project", str(project_root), "--title", "Quality"]).stdout.strip()
    wi = run(
        py("job_add.py")
        + ["--project", str(project_root), "--workstream", ws, "--title", "Quality Target", "--stakes", "normal"]
    ).stdout.strip()

    planned_check = run(py("plan_check.py") + ["--project", str(project_root)], check=False)
    if planned_check.returncode != 0:
        raise RuntimeError("Expected planned-state plan_check to pass with warnings")
    planned_text = (planned_check.stdout or "") + "\n" + (planned_check.stderr or "")
    if "WARNINGS:" not in planned_text or "content-quality" not in planned_text:
        raise RuntimeError("Expected content-quality warnings in planned-state plan_check output")

    set_frontmatter(
        project_root / "plan.md",
        agreement_status="agreed",
        agreed_at=now_iso(),
        agreed_notes="content quality test",
        status="in_progress",
        updated_at=now_iso(),
    )

    run(
        py("job_start.py")
        + [
            "--project",
            str(project_root),
            "--work-item-id",
            wi,
            "--no-apply-lessons",
            "--no-open",
            "--no-monitor",
        ]
    )

    strict_fail = run(py("plan_check.py") + ["--project", str(project_root)], check=False)
    if strict_fail.returncode == 0:
        raise RuntimeError("Expected plan_check to fail for in_progress job with placeholder lessons")
    strict_text = (strict_fail.stdout or "") + "\n" + (strict_fail.stderr or "")
    if "content-quality: relevant lessons section is empty/placeholder" not in strict_text:
        raise RuntimeError("Expected strict content-quality error for placeholder lessons section")

    run(py("lessons_apply.py") + ["--project", str(project_root), "--work-item-id", wi, "--limit", "2"])
    final_check = run(py("plan_check.py") + ["--project", str(project_root)], check=False)
    if final_check.returncode != 0:
        raise RuntimeError(
            "Expected plan_check to pass after lessons_apply resolved strict content-quality gate:\n"
            + (final_check.stdout or "")
            + "\n"
            + (final_check.stderr or "")
        )

    print("PLAN CHECK CONTENT QUALITY TEST PASSED")
    print(str(project_root))
    tmp.cleanup()


if __name__ == "__main__":
    main()
