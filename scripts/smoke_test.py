#!/usr/bin/env python3
from __future__ import annotations

import argparse
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


def run(cmd: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["THEWORKSHOP_NO_OPEN"] = "1"
    env["THEWORKSHOP_NO_MONITOR"] = "1"
    env["THEWORKSHOP_NO_KEYCHAIN"] = "1"
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, capture_output=True, env=env)
    if check and proc.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            f"  cmd={' '.join(cmd)}\n"
            f"  exit={proc.returncode}\n"
            f"  stdout:\n{proc.stdout}\n"
            f"  stderr:\n{proc.stderr}\n"
        )
    return proc


def py(script: str) -> list[str]:
    return [sys.executable, str(SCRIPTS_DIR / script)]


def find_single(glob_iter) -> Path:
    items = list(glob_iter)
    if len(items) != 1:
        raise RuntimeError(f"Expected exactly 1 match, got {len(items)}: {items}")
    return items[0]


def set_frontmatter(path: Path, **updates) -> None:
    doc = split_frontmatter(path.read_text(encoding="utf-8", errors="ignore"))
    for k, v in updates.items():
        doc.frontmatter[k] = v
    path.write_text(join_frontmatter(doc), encoding="utf-8")


def replace_section(body: str, heading: str, new_lines: list[str]) -> str:
    lines = body.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.strip() == heading.strip():
            start = i
            break
    if start is None:
        # Append missing section.
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


def update_job_plan_body(job_plan: Path, lesson_id: str) -> None:
    doc = split_frontmatter(job_plan.read_text(encoding="utf-8", errors="ignore"))
    body = doc.body
    body = replace_section(
        body,
        "# Acceptance Criteria",
        [
            "- `outputs/primary.md` exists and contains at least one paragraph.",
            "- `artifacts/verification.md` exists and references the output.",
        ],
    )
    body = replace_section(
        body,
        "# Verification",
        [
            "- Confirm `outputs/primary.md` and `artifacts/verification.md` exist and are non-empty.",
            "- Write a short verification note and timestamp into `artifacts/verification.md`.",
        ],
    )
    body = replace_section(
        body,
        "# Relevant Lessons Learned",
        [
            f"- Applied: {lesson_id} (verification evidence must be explicit and non-empty).",
        ],
    )
    doc.body = body
    job_plan.write_text(join_frontmatter(doc), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="TheWorkshop smoke test (creates a temp project, runs checks).")
    parser.add_argument("--keep", action="store_true", help="Keep the temp project directory")
    parser.add_argument("--base-dir", help="Override base dir (default: temp dir)")
    args = parser.parse_args()

    base_dir = Path(args.base_dir).expanduser().resolve() if args.base_dir else None
    tmp = None
    if base_dir is None:
        tmp = tempfile.TemporaryDirectory(prefix="theworkshop-smoke-")
        base_dir = Path(tmp.name).resolve()
    base_dir.mkdir(parents=True, exist_ok=True)

    print(f"[1] Base dir: {base_dir}")

    # Create project
    proj = run(py("project_new.py") + ["--name", "TheWorkshop Smoke Test", "--base-dir", str(base_dir)]).stdout.strip()
    project_root = Path(proj).resolve()
    print(f"[2] Project: {project_root}")

    # Add workstream
    ws_id = run(py("workstream_add.py") + ["--project", str(project_root), "--title", "Research"]).stdout.strip()
    print(f"[3] Workstream: {ws_id}")

    # Add job
    wi_id = run(
        py("job_add.py")
        + ["--project", str(project_root), "--workstream", ws_id, "--title", "Draft brief", "--stakes", "normal"]
    ).stdout.strip()
    print(f"[4] Job: {wi_id}")

    # Plan check (should pass; no execution yet)
    run(py("plan_check.py") + ["--project", str(project_root)])
    print("[5] plan_check: OK")

    # Build tracker + rewards + dashboard
    run(py("task_tracker_build.py") + ["--project", str(project_root)])
    run(py("reward_eval.py") + ["--project", str(project_root)])
    run(py("dashboard_build.py") + ["--project", str(project_root)])
    run(py("optimize_plan.py") + ["--project", str(project_root)])
    run(py("usage_snapshot.py") + ["--project", str(project_root)])
    print("[6] tracker/rewards/dashboard/optimize/usage: OK")

    # Lessons
    run(
        py("lessons_capture.py")
        + [
            "--project",
            str(project_root),
            "--tags",
            "verification,planning",
            "--linked",
            f"{wi_id},{ws_id}",
            "--context",
            "Reward gating required more explicit evidence files.",
            "--worked",
            "Declaring verification_evidence up front made checks deterministic.",
            "--failed",
            "Forgetting to generate the task tracker reduced the reward score.",
            "--recommendation",
            "Always run task_tracker_build.py early and keep outputs/evidence non-empty.",
        ]
    )
    q = run(py("lessons_query.py") + ["--project", str(project_root), "--query", "evidence", "--limit", "3"]).stdout
    if "LL-" not in q:
        raise RuntimeError("lessons_query did not return any lessons")
    # Grab the first lesson ID for linking into the job plan.
    lesson_id = ""
    for ln in q.splitlines():
        if "**LL-" in ln:
            lesson_id = ln.split("**", 2)[1]
            break
    if not lesson_id:
        lesson_id = "LL-UNKNOWN"
    print("[7] lessons: OK")

    # ws_run execution logging
    run(py("ws_run") + ["--project", str(project_root), "--label", "echo", "--work-item-id", wi_id, "--", "echo", "hello"])
    exec_log = project_root / "logs" / "execution.jsonl"
    if not exec_log.exists():
        raise RuntimeError("execution.jsonl not created")
    print("[8] ws_run logging: OK")

    # Fill in non-placeholder acceptance/verification/lessons sections so the reward can reach target.
    job_dir = find_single(project_root.glob("workstreams/WS-*/jobs/WI-*"))
    job_plan = job_dir / "plan.md"
    update_job_plan_body(job_plan, lesson_id)
    set_frontmatter(job_plan, started_at=now_iso(), iteration=1, updated_at=now_iso())

    # Gate behavior test:
    # - mark agreement as agreed + start execution
    proj_plan = project_root / "plan.md"
    set_frontmatter(
        proj_plan,
        agreement_status="agreed",
        agreed_at=now_iso(),
        agreed_notes="smoke test auto-agree",
        status="in_progress",
        updated_at=now_iso(),
    )

    # - mark job done without creating outputs/evidence => plan_check must fail with missing output/evidence
    job_doc = split_frontmatter(job_plan.read_text(encoding="utf-8", errors="ignore"))
    target = int(job_doc.frontmatter.get("reward_target") or 80)
    set_frontmatter(
        job_plan,
        status="done",
        completed_at=now_iso(),
        reward_last_score=target,
        reward_last_eval_at=now_iso(),
        updated_at=now_iso(),
    )

    proc = run(py("plan_check.py") + ["--project", str(project_root)], check=False)
    if proc.returncode == 0:
        raise RuntimeError("Expected plan_check to fail when outputs/evidence are missing for a done job")
    if "missing/empty declared output" not in (proc.stdout + proc.stderr):
        raise RuntimeError("Expected plan_check failure to mention missing/empty declared output")
    print("[9] gating missing outputs/evidence: OK (failed as expected)")

    # - create non-empty output + evidence, rerun plan_check => should pass
    (job_dir / "outputs").mkdir(parents=True, exist_ok=True)
    (job_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (job_dir / "outputs" / "primary.md").write_text("ok\n", encoding="utf-8")
    (job_dir / "artifacts" / "verification.md").write_text("verified\n", encoding="utf-8")

    # regenerate tracker/rewards/dashboard to raise reward score (and refresh next actions)
    run(py("task_tracker_build.py") + ["--project", str(project_root)])
    run(py("reward_eval.py") + ["--project", str(project_root), "--work-item-id", wi_id])
    run(py("dashboard_build.py") + ["--project", str(project_root)])

    run(py("plan_check.py") + ["--project", str(project_root)])
    print("[10] gating satisfied: OK")

    print("")
    print("SMOKE TEST PASSED")
    print(f"Project root: {project_root}")
    print(f"Dashboard: {project_root / 'outputs' / 'dashboard.html'}")

    if tmp is not None and not args.keep:
        tmp.cleanup()


if __name__ == "__main__":
    main()
