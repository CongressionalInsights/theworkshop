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


def tw() -> list[str]:
    return [sys.executable, str(SCRIPTS_DIR / "theworkshop")]


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


def status(path: Path) -> str:
    return str(split_frontmatter(path.read_text(encoding="utf-8", errors="ignore")).frontmatter.get("status") or "")


def create_project(base: Path, name: str) -> Path:
    return Path(run(py("project_new.py") + ["--name", name, "--base-dir", str(base)]).stdout.strip())


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="theworkshop-alias-compat-") as td:
        base = Path(td).resolve()

        p1 = create_project(base, "Alias close")
        set_frontmatter(p1 / "plan.md", agreement_status="agreed", agreed_at=now_iso(), agreed_notes="a", status="in_progress")
        run(tw() + ["project-close", "--project", str(p1), "--status", "cancelled", "--reason", "alias test"])
        if status(p1 / "plan.md") != "cancelled":
            raise RuntimeError("project-close alias did not cancel project")

        p2 = create_project(base, "Alias complete")
        set_frontmatter(p2 / "plan.md", agreement_status="agreed", agreed_at=now_iso(), agreed_notes="b", status="in_progress")
        run(tw() + ["project-complete", "--project", str(p2), "--no-open"])
        if status(p2 / "plan.md") != "done":
            raise RuntimeError("project-complete alias did not mark project done")

        p3 = create_project(base, "Transition direct")
        set_frontmatter(p3 / "plan.md", agreement_status="agreed", agreed_at=now_iso(), agreed_notes="c", status="in_progress")
        run(
            tw()
            + [
                "transition",
                "--project",
                str(p3),
                "--entity-kind",
                "project",
                "--to-status",
                "done",
                "--reason",
                "alias direct",
            ]
        )
        if status(p3 / "plan.md") != "done":
            raise RuntimeError("transition command did not mark project done")

        print("ALIAS COMPAT TEST PASSED")


if __name__ == "__main__":
    main()
