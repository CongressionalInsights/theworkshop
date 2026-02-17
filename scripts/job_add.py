#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from twlib import (
    ensure_dir,
    kebab,
    list_job_dirs,
    list_workstream_dirs,
    read_md,
    load_job,
    normalize_str_list,
    next_id,
    now_iso,
    render_workstream_jobs_table,
    replace_marker_block,
    resolve_project_root,
    today_yyyymmdd,
    write_md,
)
from twyaml import MarkdownDoc


JOB_TABLE_START = "<!-- THEWORKSHOP:JOB_TABLE_START -->"
JOB_TABLE_END = "<!-- THEWORKSHOP:JOB_TABLE_END -->"


def existing_wi_ids(project_root: Path, date: str) -> list[str]:
    out: list[str] = []
    for ws_dir in list_workstream_dirs(project_root):
        for job_dir in list_job_dirs(ws_dir):
            name = job_dir.name
            if name.startswith(f"WI-{date}-"):
                parts = name.split("-", 3)
                if len(parts) >= 3:
                    out.append("-".join(parts[:3]))
    return out


def stakes_defaults(stakes: str) -> tuple[int, int]:
    s = stakes.strip().lower()
    if s == "low":
        return 70, 2
    if s == "high":
        return 90, 5
    if s == "critical":
        return 95, 7
    return 80, 3


def build_job_plan(wi: str, title: str, *, depends_on: list[str], wave_id: str, stakes: str, estimate_hours: float) -> MarkdownDoc:
    ts = now_iso()
    reward_target, max_iter = stakes_defaults(stakes)
    fm = {
        "schema": "theworkshop.plan.v1",
        "kind": "job",
        "work_item_id": wi,
        "title": title,
        "status": "planned",
        "depends_on": depends_on,
        "wave_id": wave_id,
        "priority": 2,
        "estimate_hours": estimate_hours,
        "due_date": "",
        "stakes": stakes,
        "reward_target": reward_target,
        "max_iterations": max_iter,
        "iteration": 0,
        "rework_count": 0,
        "rework_reason": "",
        "started_at": "",
        "updated_at": ts,
        "completed_at": "",
        "completion_promise": f"{wi}-DONE",
        "outputs": [
            "outputs/primary.md",
        ],
        "verification_evidence": [
            "artifacts/verification.md",
        ],
        "reward_last_score": 0,
        "reward_last_eval_at": "",
        "reward_last_next_action": "",
        "github_issue_number": "",
        "github_issue_url": "",
        "truth_mode": "strict",
        "truth_checks": [
            "exists_nonempty",
            "freshness",
            "required_command_logged",
            "verification_consistency",
        ],
        "truth_required_commands": [],
        "truth_last_status": "unknown",
        "truth_last_checked_at": "",
        "truth_last_failures": [],
        "truth_input_snapshot": "artifacts/input-snapshot.json",
        "orchestration_mode": "auto",
        "agent_type_hint": "worker",
        "parallel_group": "",
    }

    body = "\n".join(
        [
            "# Objective",
            "",
            "_State the objective for this job._",
            "",
            "# Inputs",
            "",
            "_List required inputs (files, links, constraints)._",
            "",
            "# Outputs",
            "",
            "_List outputs and where they will live (match `outputs:` frontmatter)._",
            "",
            "# Acceptance Criteria",
            "",
            "- _Make these objective and checkable._",
            "",
            "# Verification",
            "",
            "_Describe how we will prove acceptance criteria are satisfied, and what evidence files will be written._",
            "",
            "# Success Hook",
            "",
            f"- Completion promise: `<promise>{wi}-DONE</promise>`",
            "",
            "# Tasks",
            "",
            "- [ ] _Optional checklist items_",
            "",
            "# Progress Log",
            "",
            f"- {ts} created job",
            "",
            "# Notes / Edge Cases",
            "",
            "",
            "# Relevant Lessons Learned",
            "",
            "_To be filled at job start by lessons retrieval._",
            "",
        ]
    )

    return MarkdownDoc(frontmatter=fm, body=body)


def build_job_prompt(wi: str, title: str) -> str:
    return "\n".join(
        [
            f"You are working on Job {wi}: {title}",
            "",
            "Follow the job plan.md (objective, acceptance criteria, verification).",
            "",
            "Only when all acceptance criteria are satisfied and verification evidence exists, output:",
            f"<promise>{wi}-DONE</promise>",
            "",
        ]
    )


def resolve_workstream_dir(project_root: Path, ws_id: str) -> Path:
    for ws_dir in list_workstream_dirs(project_root):
        if ws_dir.name.startswith(ws_id):
            return ws_dir
    raise SystemExit(f"Workstream not found: {ws_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Add a TheWorkshop job (work item) to a workstream.")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--workstream", required=True, help="Workstream ID (WS-...)")
    parser.add_argument("--title", required=True, help="Job title")
    parser.add_argument("--slug", help="Optional slug override")
    parser.add_argument("--depends-on", action="append", default=[], help="Dependency WI-... (repeatable)")
    parser.add_argument("--wave-id", default="", help="Optional wave ID (WV-...)")
    parser.add_argument("--stakes", default="normal", choices=["low", "normal", "high", "critical"], help="Reward stakes")
    parser.add_argument("--estimate-hours", type=float, default=1.0, help="Rough estimate hours (default 1.0)")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    ws_dir = resolve_workstream_dir(project_root, args.workstream)

    date = today_yyyymmdd()
    wi = next_id("WI", date, existing_wi_ids(project_root, date))
    slug = kebab(args.slug) if args.slug else kebab(args.title)
    job_dir = ws_dir / "jobs" / f"{wi}-{slug}"

    ensure_dir(job_dir)
    for d in ["inputs", "outputs", "notes", "logs", "artifacts"]:
        ensure_dir(job_dir / d)

    write_md(job_dir / "plan.md", build_job_plan(wi, args.title, depends_on=args.depends_on, wave_id=args.wave_id, stakes=args.stakes, estimate_hours=args.estimate_hours))
    (job_dir / "prompt.md").write_text(build_job_prompt(wi, args.title), encoding="utf-8")

    # Update workstream plan frontmatter + jobs table
    ws_plan_path = ws_dir / "plan.md"
    ws_doc = read_md(ws_plan_path)  # preserve ordering as best-effort
    jobs_list = normalize_str_list(ws_doc.frontmatter.get("jobs"))
    if wi not in jobs_list:
        jobs_list.append(wi)
    ws_doc.frontmatter["jobs"] = jobs_list
    ws_doc.frontmatter["updated_at"] = now_iso()

    jobs = [load_job(p) for p in list_job_dirs(ws_dir)]
    table = render_workstream_jobs_table(jobs)
    ws_doc.body = replace_marker_block(ws_doc.body, JOB_TABLE_START, JOB_TABLE_END, table)
    write_md(ws_plan_path, ws_doc)

    # Update project updated_at
    proj_plan_path = project_root / "plan.md"
    proj_doc = read_md(proj_plan_path)
    proj_doc.frontmatter["updated_at"] = now_iso()
    write_md(proj_plan_path, proj_doc)

    print(wi)


if __name__ == "__main__":
    main()
