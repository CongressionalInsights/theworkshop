#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

# Allow importing TheWorkshop helpers from the scripts directory.
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from twlib import now_iso  # noqa: E402
from twyaml import join_frontmatter, split_frontmatter  # noqa: E402


LL_RE = re.compile(r"^##\s+(LL-[0-9]{8}-[0-9]{3})\b")


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


def set_frontmatter(path: Path, **updates) -> None:
    doc = split_frontmatter(path.read_text(encoding="utf-8", errors="ignore"))
    for k, v in updates.items():
        doc.frontmatter[k] = v
    path.write_text(join_frontmatter(doc), encoding="utf-8")


def last_lesson_id(lessons_md: Path) -> str:
    if not lessons_md.exists():
        return ""
    last = ""
    for ln in lessons_md.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = LL_RE.match(ln.strip())
        if m:
            last = m.group(1)
    return last


def find_job_dir(project_root: Path, wi: str) -> Path:
    matches = list(project_root.glob(f"workstreams/WS-*/jobs/{wi}-*"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected 1 job dir for {wi}, got {len(matches)}: {matches}")
    return matches[0]


def patch_project_plan(project_root: Path, waves: list[dict]) -> None:
    plan = project_root / "plan.md"
    doc = split_frontmatter(plan.read_text(encoding="utf-8", errors="ignore"))
    ts = now_iso()

    doc.frontmatter["waves"] = waves
    doc.frontmatter["agreement_status"] = "agreed"
    doc.frontmatter["agreed_at"] = ts
    doc.frontmatter["agreed_notes"] = "Synthetic demo: auto-agreed to enable execution state testing."
    doc.frontmatter["status"] = "in_progress"
    doc.frontmatter["updated_at"] = ts

    body = doc.body
    body = replace_section(
        body,
        "# Goal",
        [
            "Demonstrate TheWorkshop control plane on a non-coding project:",
            "- optimized decomposition (project -> workstreams -> jobs)",
            "- waves + dependencies",
            "- behavior-driving rewards",
            "- lessons learned capture + retrieval",
            "- mini dashboard and tracker artifacts",
        ],
    )
    body = replace_section(
        body,
        "# Acceptance Criteria",
        [
            "- At least 2 jobs are `done` with declared outputs + verification evidence present.",
            "- `scripts/plan_check.py` passes.",
            "- `outputs/dashboard.html` exists and shows workstreams/jobs with statuses.",
            "- `outputs/*-task-tracker.csv` exists with one row per job.",
            "- `outputs/reward-report.md` exists and shows reward next-action hints.",
        ],
    )
    body = replace_section(
        body,
        "# Decisions",
        [
            f"- {ts}: Using a synthetic project to exercise success hooks + reward gating without external dependencies.",
            f"- {ts}: Keeping GitHub mirroring disabled for this demo (no remote repo).",
        ],
    )
    doc.body = body
    plan.write_text(join_frontmatter(doc), encoding="utf-8")


def patch_workstream_plan(ws_plan: Path, *, purpose: str, status: str) -> None:
    doc = split_frontmatter(ws_plan.read_text(encoding="utf-8", errors="ignore"))
    ts = now_iso()
    doc.frontmatter["status"] = status
    doc.frontmatter["updated_at"] = ts
    doc.body = replace_section(doc.body, "# Purpose (How This Supports The Project Goal)", [purpose])
    doc.body = replace_section(doc.body, "# Dependencies", ["- (synthetic demo)"])
    ws_plan.write_text(join_frontmatter(doc), encoding="utf-8")


def patch_job_plan(job_plan: Path, *, lesson_id: str, objective: str, acceptance: list[str], verification: list[str]) -> None:
    doc = split_frontmatter(job_plan.read_text(encoding="utf-8", errors="ignore"))
    ts = now_iso()
    doc.body = replace_section(doc.body, "# Objective", [objective])
    doc.body = replace_section(doc.body, "# Outputs", ["- `outputs/primary.md`", "- `artifacts/verification.md`"])
    doc.body = replace_section(doc.body, "# Acceptance Criteria", acceptance)
    doc.body = replace_section(doc.body, "# Verification", verification)
    doc.body = replace_section(
        doc.body,
        "# Relevant Lessons Learned",
        [f"- Applied: {lesson_id} (make verification evidence explicit and non-empty)."] if lesson_id else ["- (none yet)"],
    )
    # Keep a small progress breadcrumb.
    doc.body = replace_section(doc.body, "# Progress Log", [f"- {ts} updated job plan for synthetic demo"])
    doc.frontmatter["updated_at"] = ts
    job_plan.write_text(join_frontmatter(doc), encoding="utf-8")


def write_job_artifacts(job_dir: Path, *, output_text: str, evidence_text: str) -> None:
    (job_dir / "outputs").mkdir(parents=True, exist_ok=True)
    (job_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (job_dir / "outputs" / "primary.md").write_text(output_text.rstrip() + "\n", encoding="utf-8")
    (job_dir / "artifacts" / "verification.md").write_text(evidence_text.rstrip() + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a synthetic TheWorkshop project that exercises key capabilities.")
    parser.add_argument("--base-dir", help="Where to create the project (default: <repo>/_test_runs)")
    parser.add_argument("--name", default="TheWorkshop Synthetic Demo", help="Project title")
    parser.add_argument("--slug", default="synthetic-demo", help="Project directory slug override")
    args = parser.parse_args()

    repo_root = SCRIPTS_DIR.parent
    base_dir = Path(args.base_dir).expanduser().resolve() if args.base_dir else (repo_root / "_test_runs")
    base_dir.mkdir(parents=True, exist_ok=True)

    # 1) Create project root.
    proj = run(py("project_new.py") + ["--name", args.name, "--base-dir", str(base_dir), "--slug", args.slug]).stdout.strip()
    project_root = Path(proj).resolve()

    # 2) Workstreams (with dependencies).
    ws1 = run(py("workstream_add.py") + ["--project", str(project_root), "--title", "Intake & Decomposition"]).stdout.strip()
    ws2 = run(
        py("workstream_add.py")
        + ["--project", str(project_root), "--title", "Execution (Artifacts + Verification)", "--depends-on", ws1]
    ).stdout.strip()
    ws3 = run(
        py("workstream_add.py")
        + ["--project", str(project_root), "--title", "Closeout (Lessons + Dashboard)", "--depends-on", ws2]
    ).stdout.strip()

    # 3) Add waves + mark agreement so we can set execution states.
    waves = [
        {"id": "WV-20260214-001", "title": "Wave 1: Decompose", "start": "2026-02-14", "end": "2026-02-14"},
        {"id": "WV-20260214-002", "title": "Wave 2: Execute", "start": "2026-02-14", "end": "2026-02-14"},
        {"id": "WV-20260214-003", "title": "Wave 3: Closeout", "start": "2026-02-14", "end": "2026-02-14"},
    ]
    patch_project_plan(project_root, waves)

    # 4) Jobs with dependencies + waves.
    wi1 = run(
        py("job_add.py")
        + ["--project", str(project_root), "--workstream", ws1, "--title", "Define deliverables + success hooks", "--wave-id", "WV-20260214-001", "--stakes", "normal"]
    ).stdout.strip()
    wi2 = run(
        py("job_add.py")
        + ["--project", str(project_root), "--workstream", ws1, "--title", "Optimize ordering + dependencies", "--wave-id", "WV-20260214-001", "--stakes", "normal", "--depends-on", wi1]
    ).stdout.strip()
    wi3 = run(
        py("job_add.py")
        + ["--project", str(project_root), "--workstream", ws2, "--title", "Produce primary artifact draft", "--wave-id", "WV-20260214-002", "--stakes", "high", "--depends-on", wi2, "--estimate-hours", "6.5"]
    ).stdout.strip()
    wi4 = run(
        py("job_add.py")
        + ["--project", str(project_root), "--workstream", ws2, "--title", "Verification pass + evidence capture", "--wave-id", "WV-20260214-002", "--stakes", "high", "--depends-on", wi3]
    ).stdout.strip()
    wi5 = run(
        py("job_add.py")
        + ["--project", str(project_root), "--workstream", ws3, "--title", "Capture lessons + closeout", "--wave-id", "WV-20260214-003", "--stakes", "normal", "--depends-on", wi4]
    ).stdout.strip()

    # 5) Capture a lesson, then wire it into the done jobs.
    run(
        py("lessons_capture.py")
        + [
            "--project",
            str(project_root),
            "--tags",
            "planning,verification,rewards",
            "--linked",
            f"{wi1},{wi2},{ws1}",
            "--context",
            "Synthetic demo jobs should have explicit outputs + explicit verification evidence to satisfy reward gates.",
            "--worked",
            "Declaring outputs and verification_evidence paths up front made checks deterministic.",
            "--failed",
            "Leaving placeholder acceptance/verification text caused low reward scores.",
            "--recommendation",
            "Always replace placeholder plan sections before attempting to mark a job done.",
        ]
    )
    lesson_id = last_lesson_id(project_root / "notes" / "lessons-learned.md")

    # 6) Patch workstream plans (purpose + status).
    patch_workstream_plan(
        project_root / "workstreams" / next(p.name for p in (project_root / "workstreams").iterdir() if p.name.startswith(ws1)) / "plan.md",
        purpose="Define the optimized decomposition, success hooks, and dependencies so later jobs are verifiable and loopable.",
        status="in_progress",
    )
    patch_workstream_plan(
        project_root / "workstreams" / next(p.name for p in (project_root / "workstreams").iterdir() if p.name.startswith(ws2)) / "plan.md",
        purpose="Execute work with declared outputs and verification evidence so reward gating can truthfully pass.",
        status="in_progress",
    )
    patch_workstream_plan(
        project_root / "workstreams" / next(p.name for p in (project_root / "workstreams").iterdir() if p.name.startswith(ws3)) / "plan.md",
        purpose="Close out: capture lessons learned, refresh dashboard, and leave the project in a consistent state.",
        status="planned",
    )

    # 7) Patch job plans and create artifacts for WI-1 and WI-2, then mark them done.
    job1_dir = find_job_dir(project_root, wi1)
    job2_dir = find_job_dir(project_root, wi2)
    job3_dir = find_job_dir(project_root, wi3)

    patch_job_plan(
        job1_dir / "plan.md",
        lesson_id=lesson_id,
        objective="Replace placeholders with objective, checkable acceptance criteria and an explicit verification plan.",
        acceptance=[
            "- `outputs/primary.md` exists and contains at least one paragraph describing deliverables + success hooks.",
            "- `artifacts/verification.md` exists and references the output file.",
        ],
        verification=[
            "- Confirm `outputs/primary.md` and `artifacts/verification.md` exist and are non-empty.",
            "- Ensure the output includes a completion promise string for the project/job IDs.",
            "- Record a short verification note and timestamp into `artifacts/verification.md`.",
        ],
    )
    write_job_artifacts(
        job1_dir,
        output_text=(
            "Synthetic deliverables:\n\n"
            "- A coherent project plan with workstreams/jobs and success hooks.\n"
            "- A dashboard and task tracker reflecting current status.\n\n"
            "Completion promises:\n\n"
            f"- <promise>{wi1}-DONE</promise>\n"
        ),
        evidence_text=f"Verified outputs present and non-empty at {now_iso()}.\nLinked lesson: {lesson_id}\n",
    )

    patch_job_plan(
        job2_dir / "plan.md",
        lesson_id=lesson_id,
        objective="Demonstrate ordering/dependency optimization using explicit depends_on and wave_id fields.",
        acceptance=[
            "- Job dependencies are encoded via `depends_on` frontmatter and visible on the dashboard.",
            "- `outputs/primary.md` exists and explains the intended execution order and critical path.",
            "- `artifacts/verification.md` exists and confirms `scripts/plan_check.py` passes.",
        ],
        verification=[
            "- Run `scripts/plan_check.py` (captured in execution logs) and confirm it exits 0.",
            "- Confirm dashboard shows dependency ordering and wave assignments.",
        ],
    )
    write_job_artifacts(
        job2_dir,
        output_text=(
            "Optimized order (synthetic):\n\n"
            f"1. {wi1}\n"
            f"2. {wi2}\n"
            f"3. {wi3}\n"
            f"4. {wi4}\n"
            f"5. {wi5}\n"
        ),
        evidence_text=f"Planned dependency order documented at {now_iso()}.\n",
    )

    # 8) Start jobs via lifecycle scripts (keeps iteration/progress logs consistent).
    run(py("job_start.py") + ["--project", str(project_root), "--work-item-id", wi1])
    run(
        py("job_start.py")
        + [
            "--project",
            str(project_root),
            "--work-item-id",
            wi2,
            "--allow-unmet-deps",
            "--decision-note",
            "Synthetic scenario: start WI-2 early to exercise dependency override path.",
        ]
    )
    run(
        py("job_start.py")
        + [
            "--project",
            str(project_root),
            "--work-item-id",
            wi3,
            "--allow-unmet-deps",
            "--decision-note",
            "Synthetic scenario: keep WI-3 intentionally incomplete for dashboard visibility.",
        ]
    )  # intentionally incomplete

    # Build tracker + dashboard, then run some logged commands.
    run(py("task_tracker_build.py") + ["--project", str(project_root)])
    run(py("dashboard_build.py") + ["--project", str(project_root)])

    run(
        py("ws_run")
        + [
            "--project",
            str(project_root),
            "--label",
            "plan_check",
            "--work-item-id",
            wi2,
            "--phase",
            "validate",
            "--",
            sys.executable,
            str(SCRIPTS_DIR / "plan_check.py"),
            "--project",
            str(project_root),
        ]
    )
    run(
        py("ws_run")
        + [
            "--project",
            str(project_root),
            "--label",
            "echo",
            "--work-item-id",
            wi1,
            "--phase",
            "execute",
            "--",
            "echo",
            "synthetic job execution log",
        ]
    )

    # 9) Complete WI-1 and WI-2 via reward-gated lifecycle. WI-2 cascades to close WS-1 when eligible.
    run(py("job_complete.py") + ["--project", str(project_root), "--work-item-id", wi1])
    run(py("job_complete.py") + ["--project", str(project_root), "--work-item-id", wi2, "--cascade"])

    # Refresh dashboard post-closeouts.
    run(py("dashboard_build.py") + ["--project", str(project_root)])
    run(py("optimize_plan.py") + ["--project", str(project_root)])
    run(py("usage_snapshot.py") + ["--project", str(project_root)])

    # Final consistency gate.
    run(py("plan_check.py") + ["--project", str(project_root)])

    print(str(project_root))
    print(str(project_root / "outputs" / "dashboard.html"))


if __name__ == "__main__":
    main()
