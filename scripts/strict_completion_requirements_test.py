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


def read_frontmatter(path: Path) -> dict:
    return split_frontmatter(path.read_text(encoding="utf-8", errors="ignore")).frontmatter


def replace_section(body: str, heading: str, new_lines: list[str]) -> str:
    lines = body.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.strip() == heading.strip():
            start = i
            break
    if start is None:
        return body.rstrip() + "\n\n" + heading + "\n\n" + "\n".join(new_lines).rstrip() + "\n"
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("# "):
            end = i
            break
    out = lines[: start + 1]
    out.append("")
    out.extend(new_lines)
    out.append("")
    out.extend(lines[end:])
    return "\n".join(out).rstrip() + "\n"


def find_job_dir(project_root: Path, wi: str) -> Path:
    matches = list(project_root.glob(f"workstreams/WS-*/jobs/{wi}-*"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one job dir for {wi}, got {len(matches)}")
    return matches[0]


def create_project(base_dir: Path, *, name: str) -> tuple[Path, str, Path, Path]:
    project_root = Path(run(py("project_new.py") + ["--name", name, "--base-dir", str(base_dir)]).stdout.strip()).resolve()
    ws_id = run(py("workstream_add.py") + ["--project", str(project_root), "--title", "WS"]).stdout.strip()
    wi = run(py("job_add.py") + ["--project", str(project_root), "--workstream", ws_id, "--title", "Strict Gate"]).stdout.strip()
    set_frontmatter(
        project_root / "plan.md",
        agreement_status="agreed",
        agreed_at=now_iso(),
        agreed_notes="strict completion requirements test",
        status="in_progress",
        updated_at=now_iso(),
    )

    job_dir = find_job_dir(project_root, wi)
    plan_path = job_dir / "plan.md"
    doc = split_frontmatter(plan_path.read_text(encoding="utf-8", errors="ignore"))
    doc.frontmatter["outputs"] = ["outputs/primary.md"]
    doc.frontmatter["verification_evidence"] = ["artifacts/verification.md"]
    doc.frontmatter["reward_target"] = 0
    doc.frontmatter["execution_log_required"] = True
    doc.frontmatter["execution_log_exemption_reason"] = ""
    doc.frontmatter["lesson_capture_required"] = True
    doc.frontmatter["lesson_capture_exemption_reason"] = ""
    doc.frontmatter["truth_required_commands"] = []
    doc.body = replace_section(doc.body, "# Objective", ["Validate strict execution and lesson completion requirements."])
    doc.body = replace_section(
        doc.body,
        "# Acceptance Criteria",
        [
            "- `outputs/primary.md` exists and is non-empty.",
            f"- Completion emits `<promise>{wi}-DONE</promise>`.",
        ],
    )
    doc.body = replace_section(
        doc.body,
        "# Verification",
        [
            "- Keep verification evidence in `artifacts/verification.md`.",
            "- Ensure truth and reward checks pass before completion.",
        ],
    )
    plan_path.write_text(join_frontmatter(doc), encoding="utf-8")

    (job_dir / "outputs").mkdir(parents=True, exist_ok=True)
    (job_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (job_dir / "outputs" / "primary.md").write_text(
        f"# Output\n\nReady.\n\n<promise>{wi}-DONE</promise>\n",
        encoding="utf-8",
    )
    (job_dir / "artifacts" / "verification.md").write_text(
        "# Verification\n\nEvidence exists and is non-empty.\n",
        encoding="utf-8",
    )
    return project_root, wi, job_dir, plan_path


def start_job(project_root: Path, wi: str) -> None:
    run(
        py("job_start.py")
        + [
            "--project",
            str(project_root),
            "--work-item-id",
            wi,
            "--no-open",
            "--no-apply-lessons",
        ]
    )


def log_execution(project_root: Path, wi: str) -> None:
    run(
        py("ws_run")
        + [
            "--project",
            str(project_root),
            "--label",
            "strict-evidence",
            "--work-item-id",
            wi,
            "--phase",
            "validate",
            "--",
            "echo",
            "ok",
        ]
    )


def capture_lesson(project_root: Path, wi: str) -> None:
    run(
        py("lessons_capture.py")
        + [
            "--project",
            str(project_root),
            "--tags",
            "testing,strict-gates",
            "--linked",
            wi,
            "--context",
            "Strict gate test run",
            "--worked",
            "Captured concrete evidence and verified gate behavior",
            "--recommendation",
            "Link at least one substantive lesson for strict jobs",
        ]
    )


def assert_completion_fails(project_root: Path, wi: str, plan_path: Path, reason_hint: str) -> None:
    failed = run(py("job_complete.py") + ["--project", str(project_root), "--work-item-id", wi, "--no-open"], check=False)
    if failed.returncode == 0:
        raise RuntimeError("Expected job_complete to fail")
    merged = (failed.stdout or "") + "\n" + (failed.stderr or "")
    if reason_hint not in merged:
        raise RuntimeError(f"Expected failure hint {reason_hint!r}, got:\n{merged}")
    status = str(read_frontmatter(plan_path).get("status") or "")
    if status == "done":
        raise RuntimeError("Job must not be done after failed completion")


def assert_completion_succeeds(project_root: Path, wi: str, plan_path: Path) -> None:
    run(py("job_complete.py") + ["--project", str(project_root), "--work-item-id", wi, "--no-open"])
    status = str(read_frontmatter(plan_path).get("status") or "")
    if status != "done":
        raise RuntimeError(f"Expected done status, got {status!r}")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="theworkshop-strict-completion-") as td:
        base_dir = Path(td).resolve()

        p1, wi1, _job1, plan1 = create_project(base_dir, name="Strict Missing Both")
        start_job(p1, wi1)
        assert_completion_fails(p1, wi1, plan1, "work_item_execution_logged")

        p2, wi2, _job2, plan2 = create_project(base_dir, name="Strict Only Execution")
        start_job(p2, wi2)
        log_execution(p2, wi2)
        assert_completion_fails(p2, wi2, plan2, "linked_lesson_captured")

        p3, wi3, _job3, plan3 = create_project(base_dir, name="Strict Only Lesson")
        start_job(p3, wi3)
        capture_lesson(p3, wi3)
        assert_completion_fails(p3, wi3, plan3, "work_item_execution_logged")

        p4, wi4, _job4, plan4 = create_project(base_dir, name="Strict Both Present")
        start_job(p4, wi4)
        log_execution(p4, wi4)
        capture_lesson(p4, wi4)
        assert_completion_succeeds(p4, wi4, plan4)

        p5, wi5, _job5, plan5 = create_project(base_dir, name="Strict Exemptions")
        set_frontmatter(
            plan5,
            execution_log_exemption_reason="Manual execution path; no shell command available.",
            lesson_capture_exemption_reason="One-off operational fix; no reusable lesson.",
        )
        start_job(p5, wi5)
        assert_completion_succeeds(p5, wi5, plan5)

        print("STRICT COMPLETION REQUIREMENTS TEST PASSED")


if __name__ == "__main__":
    main()
