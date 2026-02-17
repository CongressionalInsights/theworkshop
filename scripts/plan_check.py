#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from truth_eval import evaluate_job_truth
from twlib import (
    STATUS_VALUES,
    STAKE_VALUES,
    list_job_dirs,
    list_workstream_dirs,
    load_job,
    load_workstream,
    parse_time,
    read_md,
    resolve_project_root,
)


PROJECT_HEADINGS = [
    "# Goal",
    "# Acceptance Criteria",
    "# Workstreams",
    "# Success Hook",
    "# Progress Log",
    "# Decisions",
]

WORKSTREAM_HEADINGS = [
    "# Purpose (How This Supports The Project Goal)",
    "# Jobs",
    "# Dependencies",
    "# Success Hook",
    "# Progress Log",
]

JOB_HEADINGS = [
    "# Objective",
    "# Inputs",
    "# Outputs",
    "# Acceptance Criteria",
    "# Verification",
    "# Success Hook",
    "# Progress Log",
    "# Relevant Lessons Learned",
]


def rollup_status(states: list[str]) -> str:
    if any(s == "in_progress" for s in states):
        return "in_progress"
    if any(s == "blocked" for s in states):
        return "blocked"
    if states and all(s in {"done", "cancelled"} for s in states):
        return "done"
    return "planned"


def heading_missing(body: str, headings: list[str]) -> list[str]:
    missing = []
    for h in headings:
        if h not in body:
            missing.append(h)
    return missing


def rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except Exception:
        return str(path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate TheWorkshop plans and hard gates.")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as errors")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    errors: list[str] = []
    warnings: list[str] = []

    project_plan = project_root / "plan.md"
    if not project_plan.exists():
        raise SystemExit(f"Missing project plan: {project_plan}")

    proj = read_md(project_plan)
    fm = proj.frontmatter

    if fm.get("schema") != "theworkshop.plan.v1":
        errors.append(f"{rel(project_root, project_plan)}: schema must be theworkshop.plan.v1")
    if fm.get("kind") != "project":
        errors.append(f"{rel(project_root, project_plan)}: kind must be project")
    for k in ["id", "title", "status", "agreement_status", "started_at", "updated_at", "completion_promise"]:
        if not fm.get(k) and fm.get(k) != False:
            errors.append(f"{rel(project_root, project_plan)}: missing/empty frontmatter {k!r}")

    status = str(fm.get("status", "")).strip()
    if status and status not in STATUS_VALUES:
        errors.append(f"{rel(project_root, project_plan)}: invalid status {status!r}")

    agree = str(fm.get("agreement_status", "")).strip()
    if agree not in {"proposed", "agreed"}:
        errors.append(f"{rel(project_root, project_plan)}: agreement_status must be proposed|agreed")

    missing = heading_missing(proj.body, PROJECT_HEADINGS)
    if missing:
        errors.append(f"{rel(project_root, project_plan)}: missing headings: {', '.join(missing)}")

    # Scan workstreams/jobs
    ws_dirs = list_workstream_dirs(project_root)
    workstreams = []
    jobs_by_ws: dict[str, list] = {}
    any_execution = status in {"in_progress", "blocked", "done"}

    for ws_dir in ws_dirs:
        ws_plan = ws_dir / "plan.md"
        if not ws_plan.exists():
            errors.append(f"{rel(project_root, ws_plan)}: missing")
            continue
        ws_doc = read_md(ws_plan)
        ws_fm = ws_doc.frontmatter
        ws_id = str(ws_fm.get("id", "")).strip()
        if ws_fm.get("schema") != "theworkshop.plan.v1":
            errors.append(f"{rel(project_root, ws_plan)}: schema must be theworkshop.plan.v1")
        if ws_fm.get("kind") != "workstream":
            errors.append(f"{rel(project_root, ws_plan)}: kind must be workstream")
        if not ws_id:
            errors.append(f"{rel(project_root, ws_plan)}: missing id")
        elif not ws_dir.name.startswith(ws_id):
            errors.append(f"{rel(project_root, ws_plan)}: id {ws_id} does not match folder {ws_dir.name}")
        ws_status = str(ws_fm.get("status", "planned")).strip()
        if ws_status not in STATUS_VALUES:
            errors.append(f"{rel(project_root, ws_plan)}: invalid status {ws_status!r}")
        if ws_status in {"in_progress", "blocked", "done"}:
            any_execution = True

        missing_ws = heading_missing(ws_doc.body, WORKSTREAM_HEADINGS)
        if missing_ws:
            errors.append(f"{rel(project_root, ws_plan)}: missing headings: {', '.join(missing_ws)}")

        workstreams.append((ws_id, ws_status, ws_dir, ws_doc))

        jobs: list = []
        for job_dir in list_job_dirs(ws_dir):
            job_plan = job_dir / "plan.md"
            if not job_plan.exists():
                errors.append(f"{rel(project_root, job_plan)}: missing")
                continue
            job_doc = read_md(job_plan)
            jfm = job_doc.frontmatter
            if jfm.get("schema") != "theworkshop.plan.v1":
                errors.append(f"{rel(project_root, job_plan)}: schema must be theworkshop.plan.v1")
            if jfm.get("kind") != "job":
                errors.append(f"{rel(project_root, job_plan)}: kind must be job")
            wi = str(jfm.get("work_item_id", "")).strip()
            if not wi:
                errors.append(f"{rel(project_root, job_plan)}: missing work_item_id")
            elif not job_dir.name.startswith(wi):
                errors.append(f"{rel(project_root, job_plan)}: work_item_id {wi} does not match folder {job_dir.name}")

            j_status = str(jfm.get("status", "planned")).strip()
            if j_status not in STATUS_VALUES:
                errors.append(f"{rel(project_root, job_plan)}: invalid status {j_status!r}")
            if j_status in {"in_progress", "blocked", "done"}:
                any_execution = True

            missing_job = heading_missing(job_doc.body, JOB_HEADINGS)
            if missing_job:
                errors.append(f"{rel(project_root, job_plan)}: missing headings: {', '.join(missing_job)}")

            stakes = str(jfm.get("stakes", "")).strip()
            if stakes not in STAKE_VALUES:
                errors.append(f"{rel(project_root, job_plan)}: invalid stakes {stakes!r}")

            for rk in ["reward_target", "max_iterations", "iteration"]:
                if jfm.get(rk) is None:
                    errors.append(f"{rel(project_root, job_plan)}: missing {rk!r}")

            # Gating: if done, must have evidence and reward >= target.
            if j_status == "done":
                target = int(jfm.get("reward_target") or 0)
                score = int(jfm.get("reward_last_score") or 0)
                if score < target:
                    errors.append(
                        f"{rel(project_root, job_plan)}: status=done but reward_last_score {score} < reward_target {target}"
                    )
                if not str(jfm.get("reward_last_eval_at") or "").strip():
                    errors.append(f"{rel(project_root, job_plan)}: status=done but reward_last_eval_at is empty")
                if not str(jfm.get("completed_at") or "").strip():
                    errors.append(f"{rel(project_root, job_plan)}: status=done but completed_at is empty")

                outputs = jfm.get("outputs", []) or []
                if isinstance(outputs, str):
                    outputs = [o.strip() for o in outputs.split(",") if o.strip()]
                for out_rel in outputs:
                    p = job_dir / str(out_rel)
                    if not p.exists() or not p.is_file() or p.stat().st_size <= 0:
                        errors.append(f"{rel(project_root, job_plan)}: missing/empty declared output {out_rel}")

                evid = jfm.get("verification_evidence", []) or []
                if isinstance(evid, str):
                    evid = [e.strip() for e in evid.split(",") if e.strip()]
                for ev_rel in evid:
                    p = job_dir / str(ev_rel)
                    if not p.exists() or not p.is_file() or p.stat().st_size <= 0:
                        errors.append(f"{rel(project_root, job_plan)}: missing/empty verification evidence {ev_rel}")

                truth = evaluate_job_truth(project_root, job_dir)
                truth_status = str(truth.get("truth_status") or "fail")
                if truth_status != "pass":
                    failures = [str(x) for x in (truth.get("failures") or [])]
                    detail = "; ".join(failures[:3]) if failures else "unknown truth failure"
                    errors.append(f"{rel(project_root, job_plan)}: truth gate failed for done job: {detail}")

            # Iteration budget gate: if exceeded, must be blocked (until decision).
            try:
                iteration = int(jfm.get("iteration") or 0)
                max_iter = int(jfm.get("max_iterations") or 0)
                if max_iter and iteration > max_iter and j_status != "blocked":
                    errors.append(
                        f"{rel(project_root, job_plan)}: iteration {iteration} exceeds max_iterations {max_iter} but status is {j_status}"
                    )
            except Exception:
                warnings.append(f"{rel(project_root, job_plan)}: could not parse iteration/max_iterations as int")

            jobs.append((wi, j_status, job_dir, job_doc))

        jobs_by_ws[ws_id] = jobs

    # Agreement gate: execution requires agreement_status=agreed.
    if any_execution and agree != "agreed":
        errors.append(f"{rel(project_root, project_plan)}: agreement_status must be 'agreed' before execution begins")

    # Workstream done gate.
    for ws_id, ws_status, _ws_dir, ws_doc in workstreams:
        if ws_status == "done":
            for wi, j_status, _job_dir, _job_doc in jobs_by_ws.get(ws_id, []):
                if j_status != "done":
                    errors.append(
                        f"{rel(project_root, (_ws_dir / 'plan.md'))}: workstream done but job {wi} is {j_status}"
                    )

    # Rollup consistency checks (status should match child state).
    for ws_id, ws_status, ws_dir, _ws_doc in workstreams:
        child_states = [j_status for _wi, j_status, _job_dir, _job_doc in jobs_by_ws.get(ws_id, [])]
        expected_ws = rollup_status(child_states)
        if ws_status != expected_ws:
            errors.append(
                f"{rel(project_root, (ws_dir / 'plan.md'))}: status {ws_status!r} inconsistent with job rollup "
                f"{expected_ws!r}; run `theworkshop rollup`"
            )

    expected_project = rollup_status([ws_status for _ws_id, ws_status, _ws_dir, _ws_doc in workstreams])
    if status != expected_project:
        errors.append(
            f"{rel(project_root, project_plan)}: status {status!r} inconsistent with workstream rollup "
            f"{expected_project!r}; run `theworkshop rollup`"
        )

    # Project done gate.
    if status == "done":
        for ws_id, ws_status, _ws_dir, _ws_doc in workstreams:
            if ws_status != "done":
                errors.append(f"{rel(project_root, project_plan)}: project done but workstream {ws_id} is {ws_status}")

    # Timestamp sanity warnings
    p_started = parse_time(str(fm.get("started_at") or ""))
    if not p_started:
        warnings.append(f"{rel(project_root, project_plan)}: could not parse started_at timestamp")

    if warnings:
        print("WARNINGS:")
        for w in warnings:
            print(f"- {w}")
        print("")

    if errors or (args.strict and warnings):
        print("ERRORS:")
        for e in errors:
            print(f"- {e}")
        raise SystemExit(1)

    print("OK")


if __name__ == "__main__":
    main()
