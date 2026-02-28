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


def find_job_plan(project_root: Path, wi: str) -> Path:
    matches = list(project_root.glob(f"workstreams/WS-*/jobs/{wi}-*/plan.md"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one job plan for {wi}, got {len(matches)}")
    return matches[0]


def extract_section(body: str, heading: str) -> str:
    lines = body.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.strip() == heading:
            start = i + 1
            break
    if start is None:
        return ""
    out: list[str] = []
    for ln in lines[start:]:
        if ln.startswith("# "):
            break
        out.append(ln)
    return "\n".join(out).strip()


def main() -> None:
    tmp = tempfile.TemporaryDirectory(prefix="theworkshop-lessons-apply-")
    base_dir = Path(tmp.name).resolve()

    project_root = Path(
        run(py("project_new.py") + ["--name", "Lessons Apply Test", "--base-dir", str(base_dir)]).stdout.strip()
    ).resolve()
    ws = run(py("workstream_add.py") + ["--project", str(project_root), "--title", "Lessons"]).stdout.strip()

    wi_apply = run(
        py("job_add.py")
        + ["--project", str(project_root), "--workstream", ws, "--title", "Entity Resolution Sweep", "--stakes", "normal"]
    ).stdout.strip()
    wi_skip = run(
        py("job_add.py")
        + ["--project", str(project_root), "--workstream", ws, "--title", "Skip Auto Lessons", "--stakes", "normal"]
    ).stdout.strip()

    set_frontmatter(
        project_root / "plan.md",
        agreement_status="agreed",
        agreed_at=now_iso(),
        agreed_notes="lessons apply test",
        status="in_progress",
        updated_at=now_iso(),
    )

    # Capture one directly-linked lesson and one unrelated lesson.
    run(
        py("lessons_capture.py")
        + [
            "--project",
            str(project_root),
            "--tags",
            "identity,normalization",
            "--linked",
            wi_apply,
            "--context",
            "Entity matching task required explicit variant normalization.",
            "--worked",
            "Using canonical name tables reduced collisions.",
            "--failed",
            "Relying only on surname comparisons produced false matches.",
            "--recommendation",
            "Always create a name-variant normalization table before final attribution.",
        ]
    )
    run(
        py("lessons_capture.py")
        + [
            "--project",
            str(project_root),
            "--tags",
            "ops",
            "--linked",
            ws,
            "--context",
            "General ops lesson not specific to entity resolution.",
            "--worked",
            "N/A",
            "--failed",
            "N/A",
            "--recommendation",
            "Keep dashboard refreshed.",
        ]
    )

    q = run(
        py("lessons_query.py")
        + [
            "--project",
            str(project_root),
            "--query",
            "entity normalization table",
            "--linked",
            wi_apply,
            "--limit",
            "2",
        ]
    ).stdout
    ranked_lines = [ln for ln in q.splitlines() if ln.strip().startswith("- **LL-")]
    if not ranked_lines:
        raise RuntimeError("Expected lessons_query to return ranked lesson entries")

    plan_apply = find_job_plan(project_root, wi_apply)
    first_apply = run(py("lessons_apply.py") + ["--project", str(project_root), "--work-item-id", wi_apply, "--limit", "3"]).stdout
    if "status=updated" not in first_apply:
        raise RuntimeError("Expected first lessons_apply run to update the plan")
    second_apply = run(py("lessons_apply.py") + ["--project", str(project_root), "--work-item-id", wi_apply, "--limit", "3"]).stdout
    if "status=no_change" not in second_apply:
        raise RuntimeError("Expected second lessons_apply run to be idempotent (no_change)")

    section_apply = extract_section(
        split_frontmatter(plan_apply.read_text(encoding="utf-8", errors="ignore")).body,
        "# Relevant Lessons Learned",
    )
    if "LL-" not in section_apply:
        raise RuntimeError("Expected lessons section to include applied LL-* IDs")

    plan_skip = find_job_plan(project_root, wi_skip)
    before_skip = extract_section(
        split_frontmatter(plan_skip.read_text(encoding="utf-8", errors="ignore")).body,
        "# Relevant Lessons Learned",
    )
    run(
        py("job_start.py")
        + [
            "--project",
            str(project_root),
            "--work-item-id",
            wi_skip,
            "--no-apply-lessons",
            "--no-open",
            "--no-monitor",
        ]
    )
    after_skip = extract_section(
        split_frontmatter(plan_skip.read_text(encoding="utf-8", errors="ignore")).body,
        "# Relevant Lessons Learned",
    )
    if before_skip != after_skip:
        raise RuntimeError("Expected --no-apply-lessons to leave # Relevant Lessons Learned unchanged")

    print("LESSONS APPLY TEST PASSED")
    print(str(project_root))
    tmp.cleanup()


if __name__ == "__main__":
    main()
