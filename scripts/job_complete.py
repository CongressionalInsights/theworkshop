#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from transition import transition_entity
from tw_tools import append_section_bullet, run_script, validate_context_gate_for_job
from twlib import list_job_dirs, list_workstream_dirs, normalize_str_list, now_iso, read_md, resolve_project_root, write_md


def find_job_dir(project_root: Path, wi: str) -> Path:
    matches = list(project_root.glob(f"workstreams/WS-*/jobs/{wi}-*"))
    if len(matches) != 1:
        raise SystemExit(f"Expected exactly 1 job dir for {wi}, got {len(matches)}: {matches}")
    return matches[0]


def file_exists_nonempty(path: Path) -> bool:
    try:
        return path.exists() and path.is_file() and path.stat().st_size > 0
    except Exception:
        return False


def dependency_gate_errors(project_root: Path, fm: dict) -> list[str]:
    errors: list[str] = []
    for dep in normalize_str_list(fm.get("depends_on")):
        matches = list(project_root.glob(f"workstreams/WS-*/jobs/{dep}-*/plan.md"))
        if len(matches) != 1:
            errors.append(f"dependency gate: required dependency {dep} missing")
            continue
        dep_doc = read_md(matches[0])
        dep_status = str(dep_doc.frontmatter.get("status") or "planned").strip()
        if dep_status != "done":
            errors.append(f"dependency gate: {dep} status is {dep_status}, expected done")
    return errors


def gating_errors(project_root: Path, job_dir: Path) -> list[str]:
    doc = read_md(job_dir / "plan.md")
    fm = doc.frontmatter
    errors: list[str] = []

    context_errors, _context_warnings, _context_ref = validate_context_gate_for_job(project_root, job_dir / "plan.md")
    errors.extend([f"context gate: {msg}" for msg in context_errors])

    target = int(fm.get("reward_target") or 0)
    score = int(fm.get("reward_last_score") or 0)
    if score < target:
        errors.append(f"reward_last_score {score} < reward_target {target}")
    if not str(fm.get("reward_last_eval_at") or "").strip():
        errors.append("reward_last_eval_at is empty")
    truth_status = str(fm.get("truth_last_status") or "").strip().lower()
    if truth_status != "pass":
        errors.append(f"truth_last_status is {truth_status!r}, expected 'pass'")
    truth_failures = normalize_str_list(fm.get("truth_last_failures"))
    if truth_failures:
        errors.append("truth failures present: " + "; ".join(truth_failures[:3]))

    uat_open_issues = normalize_str_list(fm.get("uat_open_issues"))
    if uat_open_issues:
        errors.append("UAT gate: open issues present: " + "; ".join(uat_open_issues[:3]))
    uat_status = str(fm.get("uat_last_status") or "").strip().lower()
    if uat_status == "fail":
        errors.append("UAT gate: latest verify-work status is fail")

    errors.extend(dependency_gate_errors(project_root, fm))

    outputs = fm.get("outputs", []) or []
    if isinstance(outputs, str):
        outputs = [o.strip() for o in outputs.split(",") if o.strip()]
    for out_rel in outputs:
        p = job_dir / str(out_rel)
        if not file_exists_nonempty(p):
            errors.append(f"missing/empty declared output {out_rel}")

    evid = fm.get("verification_evidence", []) or []
    if isinstance(evid, str):
        evid = [e.strip() for e in evid.split(",") if e.strip()]
    for ev_rel in evid:
        p = job_dir / str(ev_rel)
        if not file_exists_nonempty(p):
            errors.append(f"missing/empty verification evidence {ev_rel}")

    return errors


def parent_workstream_dir(project_root: Path, job_dir: Path) -> Path:
    try:
        rel = job_dir.relative_to(project_root)
    except Exception:
        raise SystemExit(f"Job dir is not under project root: {job_dir}")
    parts = rel.parts
    if len(parts) < 4 or parts[0] != "workstreams" or parts[2] != "jobs":
        raise SystemExit(f"Unexpected job path layout: {rel}")
    ws_dir = project_root / parts[0] / parts[1]
    if not ws_dir.exists():
        raise SystemExit(f"Parent workstream directory not found: {ws_dir}")
    return ws_dir


def all_jobs_done(ws_dir: Path) -> bool:
    for jd in list_job_dirs(ws_dir):
        st = str(read_md(jd / "plan.md").frontmatter.get("status") or "planned").strip()
        if st != "done":
            return False
    return True


def all_workstreams_done(project_root: Path) -> bool:
    for ws_dir in list_workstream_dirs(project_root):
        st = str(read_md(ws_dir / "plan.md").frontmatter.get("status") or "planned").strip()
        if st != "done":
            return False
    return True


def append_progress_note(plan_path: Path, note: str, *, ts: str | None = None) -> None:
    stamp = ts or now_iso()
    doc = read_md(plan_path)
    doc.body = append_progress_line(doc.body, f"{stamp} {note}")
    doc.frontmatter["updated_at"] = stamp
    write_md(plan_path, doc)


def append_progress_if_noop(plan_path: Path, *, to_status: str, note: str) -> None:
    current = str(read_md(plan_path).frontmatter.get("status") or "planned").strip()
    if current == to_status:
        append_progress_note(plan_path, note)


def append_progress_line(body: str, line: str) -> str:
    return append_section_bullet(body, "# Progress Log", line)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Attempt to complete a TheWorkshop job (gate-validated + canonical transition)."
    )
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--work-item-id", required=True, help="WI-... to complete")
    parser.add_argument(
        "--cascade",
        action="store_true",
        help="If completion succeeds, auto-complete parent workstream/project when eligible.",
    )
    parser.add_argument("--no-sync", action="store_true", help="Do not run plan sync")
    parser.add_argument("--no-dashboard", action="store_true", help="Skip dashboard projection")
    parser.add_argument("--no-open", action="store_true", help="Do not open dashboard")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    wi = args.work_item_id.strip()
    job_dir = find_job_dir(project_root, wi)
    plan_path = job_dir / "plan.md"

    proj = read_md(project_root / "plan.md")
    agree = str(proj.frontmatter.get("agreement_status") or "").strip()
    if agree != "agreed":
        raise SystemExit("agreement_status must be 'agreed' before job completion (set it in project plan frontmatter).")

    ts = now_iso()
    doc = read_md(plan_path)
    prev_status = str(doc.frontmatter.get("status") or "planned").strip()
    if prev_status == "cancelled":
        raise SystemExit(f"Cannot complete cancelled job: {wi}")

    # Ensure runtime metadata exists before gate evaluation.
    if not str(doc.frontmatter.get("started_at") or "").strip():
        doc.frontmatter["started_at"] = ts
    try:
        iteration = int(doc.frontmatter.get("iteration") or 0)
    except Exception:
        iteration = 0
    if iteration <= 0:
        iteration = 1
    doc.frontmatter["iteration"] = iteration
    doc.frontmatter["updated_at"] = ts
    write_md(plan_path, doc)

    dep_errors = dependency_gate_errors(project_root, doc.frontmatter)
    if dep_errors:
        dep_note = f"job_complete: dependency gate failed; errors: {', '.join(dep_errors[:5])}"
        append_progress_if_noop(plan_path, to_status="blocked", note=dep_note)
        transition_entity(
            project_root,
            entity_kind="job",
            entity_id=wi,
            to_status="blocked",
            reason="job complete dependency gate failed",
            actor="job_complete.py",
            sync=not args.no_sync,
            refresh_dashboard=not args.no_dashboard,
            start_monitor=(not args.no_open),
            no_open=args.no_open,
            extra_progress=[dep_note],
        )
        raise SystemExit("Job completion dependency gate failed:\n- " + "\n- ".join(dep_errors))

    # Update support artifacts prior to gate checks.
    run_script("task_tracker_build.py", ["--project", str(project_root)], check=True)
    if not args.no_dashboard:
        run_script("dashboard_projector.py", ["--project", str(project_root)], check=True)
    try:
        run_script("input_snapshot.py", ["--project", str(project_root), "--work-item-id", wi], check=True)
    except Exception as exc:
        msg = f"job_complete: input_snapshot failed; blocking completion: {exc}"
        append_progress_if_noop(plan_path, to_status="blocked", note=msg)
        transition_entity(
            project_root,
            entity_kind="job",
            entity_id=wi,
            to_status="blocked",
            reason="job complete input snapshot failed",
            actor="job_complete.py",
            sync=not args.no_sync,
            refresh_dashboard=not args.no_dashboard,
            start_monitor=(not args.no_open),
            no_open=args.no_open,
            extra_progress=[msg],
        )
        raise SystemExit("Job completion input snapshot failed:\n" + str(exc))

    run_script("reward_eval.py", ["--project", str(project_root), "--no-sync", "--no-dashboard"], check=True)
    run_script("truth_eval.py", ["--project", str(project_root), "--no-sync", "--no-dashboard"], check=True)

    errors = gating_errors(project_root, job_dir)
    if errors:
        fail_status = "blocked" if any(e.startswith("dependency gate") or "snapshot stale" in e for e in errors) else "in_progress"
        fail_note = f"job_complete: gate failed; status={fail_status}; errors: {', '.join(errors[:5])}"
        append_progress_if_noop(plan_path, to_status=fail_status, note=fail_note)
        transition_entity(
            project_root,
            entity_kind="job",
            entity_id=wi,
            to_status=fail_status,
            reason="job complete gate failed",
            actor="job_complete.py",
            sync=not args.no_sync,
            refresh_dashboard=not args.no_dashboard,
            start_monitor=(not args.no_open),
            no_open=args.no_open,
            extra_progress=[fail_note],
        )
        raise SystemExit("Job completion gate failed:\n- " + "\n- ".join(errors))

    done = transition_entity(
        project_root,
        entity_kind="job",
        entity_id=wi,
        to_status="done",
        reason="job completion gates passed",
        actor="job_complete.py",
        sync=not args.no_sync,
        refresh_dashboard=not args.no_dashboard,
        start_monitor=(not args.no_open),
        no_open=args.no_open,
        extra_progress=["job_complete: gate passed; status=done confirmed"],
    )

    # Refresh reward/truth artifacts after the final done transition so reports reflect terminal state.
    try:
        run_script("reward_eval.py", ["--project", str(project_root), "--work-item-id", wi, "--no-sync", "--no-dashboard"], check=True)
    except Exception as exc:
        warning = f"job_complete warning: post-done reward_eval failed: {exc}"
        print(warning, file=sys.stderr)
        append_progress_note(plan_path, warning)
    try:
        run_script("truth_eval.py", ["--project", str(project_root), "--work-item-id", wi, "--no-sync", "--no-dashboard"], check=True)
    except Exception as exc:
        warning = f"job_complete warning: post-done truth_eval failed: {exc}"
        print(warning, file=sys.stderr)
        append_progress_note(plan_path, warning)

    extra_promises: list[str] = []
    if args.cascade:
        ws_dir = parent_workstream_dir(project_root, job_dir)
        ws_doc = read_md(ws_dir / "plan.md")
        ws_id = str(ws_doc.frontmatter.get("id") or ws_dir.name).strip()
        ws_status = str(ws_doc.frontmatter.get("status") or "planned").strip()
        if ws_status not in {"done", "cancelled"} and all_jobs_done(ws_dir):
            ws_res = transition_entity(
                project_root,
                entity_kind="workstream",
                entity_id=ws_id,
                to_status="done",
                reason="cascade after job completion",
                actor="job_complete.py",
                sync=not args.no_sync,
                refresh_dashboard=not args.no_dashboard,
                start_monitor=False,
            )
            if ws_res.promise:
                extra_promises.append(ws_res.promise)

        proj_status = str(read_md(project_root / "plan.md").frontmatter.get("status") or "planned").strip()
        if proj_status not in {"done", "cancelled"} and all_workstreams_done(project_root):
            pj_res = transition_entity(
                project_root,
                entity_kind="project",
                entity_id=None,
                to_status="done",
                reason="cascade after workstream completion",
                actor="job_complete.py",
                sync=not args.no_sync,
                refresh_dashboard=not args.no_dashboard,
                start_monitor=False,
            )
            if pj_res.promise:
                extra_promises.append(pj_res.promise)

    # Keep execution plane artifacts in sync.
    run_script("task_tracker_build.py", ["--project", str(project_root)], check=True)
    try:
        run_script(
            "invalidate_downstream.py",
            ["--project", str(project_root), "--upstream-work-item-id", wi, "--no-sync", "--no-dashboard"],
            check=True,
        )
    except Exception as exc:
        warning = f"job_complete warning: invalidate_downstream failed: {exc}"
        print(warning, file=sys.stderr)
        append_progress_note(plan_path, warning)
    try:
        run_script("orchestrate_plan.py", ["--project", str(project_root)], check=True)
    except Exception as exc:
        warning = f"job_complete warning: orchestrate_plan failed: {exc}"
        print(warning, file=sys.stderr)
        append_progress_note(plan_path, warning)
    run_script("task_tracker_build.py", ["--project", str(project_root)], check=True)
    if not args.no_dashboard:
        run_script("dashboard_projector.py", ["--project", str(project_root)], check=True)

    if done.promise:
        print(done.promise)
    for p in extra_promises:
        print(p)


if __name__ == "__main__":
    main()
