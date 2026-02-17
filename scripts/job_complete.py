#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from plan_sync import sync_project_plans
from twlib import list_job_dirs, list_workstream_dirs, normalize_str_list, now_iso, read_md, resolve_project_root, write_md


def append_progress_log(body: str, line: str) -> str:
    heading = "# Progress Log"
    if heading not in body:
        return body.rstrip() + "\n\n" + heading + "\n\n" + f"- {line}\n"
    pre, rest = body.split(heading, 1)
    rest_lines = rest.splitlines()
    insert_at = len(rest_lines)
    for i, ln in enumerate(rest_lines[1:], start=1):
        if ln.startswith("# "):
            insert_at = i
            break
    new_rest = rest_lines[:insert_at] + [f"- {line}"] + rest_lines[insert_at:]
    return (pre + heading + "\n" + "\n".join(new_rest)).rstrip() + "\n"


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


def run_py(script: str, argv: list[str]) -> None:
    scripts_dir = Path(__file__).resolve().parent
    cmd = [sys.executable, str(scripts_dir / script)] + argv
    proc = subprocess.run(cmd, text=True, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            f"  cmd={' '.join(cmd)}\n"
            f"  exit={proc.returncode}\n"
            f"  stdout:\n{proc.stdout}\n"
            f"  stderr:\n{proc.stderr}\n"
        )


def run_py_best_effort(script: str, argv: list[str]) -> None:
    try:
        run_py(script, argv)
    except Exception as exc:
        print(f"warning: {script} failed (best-effort): {exc}", file=sys.stderr)


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
    """
    job_dir is expected under: <project>/workstreams/<ws>/jobs/<wi>-...
    """
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


def try_complete_workstream(project_root: Path, ws_dir: Path, *, ts: str) -> str | None:
    ws_plan = ws_dir / "plan.md"
    if not ws_plan.exists():
        return None
    ws_doc = read_md(ws_plan)
    ws_id = str(ws_doc.frontmatter.get("id") or "").strip()
    if not ws_id:
        parts = ws_dir.name.split("-", 3)
        ws_id = "-".join(parts[:3]) if len(parts) >= 3 else ws_dir.name
    ws_status = str(ws_doc.frontmatter.get("status") or "planned").strip()
    if ws_status in {"done", "cancelled"}:
        return None

    # Eligible only if all jobs are done (consistent with plan_check gate).
    for jd in list_job_dirs(ws_dir):
        jdoc = read_md(jd / "plan.md")
        st = str(jdoc.frontmatter.get("status") or "planned").strip()
        if st != "done":
            return None

    ws_doc.frontmatter["status"] = "done"
    if not str(ws_doc.frontmatter.get("completed_at") or "").strip():
        ws_doc.frontmatter["completed_at"] = ts
    ws_doc.frontmatter["updated_at"] = ts
    ws_doc.body = append_progress_log(ws_doc.body, f"{ts} auto-complete: all jobs done; status=done")
    write_md(ws_plan, ws_doc)
    return ws_id


def try_complete_project(project_root: Path, *, ts: str) -> str | None:
    proj_plan = project_root / "plan.md"
    if not proj_plan.exists():
        return None
    proj_doc = read_md(proj_plan)
    proj_id = str(proj_doc.frontmatter.get("id") or "").strip()
    status = str(proj_doc.frontmatter.get("status") or "planned").strip()
    if status in {"done", "cancelled"}:
        return None

    # Eligible only if all workstreams are done (consistent with plan_check gate).
    for ws_dir in list_workstream_dirs(project_root):
        ws_doc = read_md(ws_dir / "plan.md")
        ws_status = str(ws_doc.frontmatter.get("status") or "planned").strip()
        if ws_status != "done":
            return None

    proj_doc.frontmatter["status"] = "done"
    if not str(proj_doc.frontmatter.get("completed_at") or "").strip():
        proj_doc.frontmatter["completed_at"] = ts
    proj_doc.frontmatter["updated_at"] = ts
    proj_doc.body = append_progress_log(proj_doc.body, f"{ts} auto-complete: all workstreams done; status=done")
    write_md(proj_plan, proj_doc)
    return proj_id or "PROJECT"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Attempt to complete a TheWorkshop job (reward-gated). Updates artifacts, runs reward eval, and only marks done if gates pass."
    )
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--work-item-id", required=True, help="WI-... to complete")
    parser.add_argument(
        "--cascade",
        action="store_true",
        help="If completion succeeds, auto-complete the parent workstream when it becomes eligible (and the project if all workstreams become done).",
    )
    parser.add_argument("--no-sync", action="store_true", help="Do not run plan_sync after completion attempt")
    parser.add_argument("--no-dashboard", action="store_true", help="Skip dashboard build (not recommended)")
    parser.add_argument("--no-open", action="store_true", help="Do not auto-open the dashboard (best-effort)")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    wi = args.work_item_id.strip()
    job_dir = find_job_dir(project_root, wi)
    plan_path = job_dir / "plan.md"

    ts = now_iso()

    # Agreement gate: execution (including completion) requires agreement_status=agreed.
    proj = read_md(project_root / "plan.md")
    agree = str(proj.frontmatter.get("agreement_status") or "").strip()
    if agree != "agreed":
        raise SystemExit("agreement_status must be 'agreed' before job completion (set it in project plan frontmatter).")

    doc = read_md(plan_path)
    prev_status = str(doc.frontmatter.get("status") or "planned").strip()
    if prev_status in {"cancelled"}:
        raise SystemExit(f"Cannot complete cancelled job: {wi}")

    # Ensure job has a started_at and at least one iteration.
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
        ts_dep_fail = now_iso()
        doc.frontmatter["status"] = "blocked"
        doc.frontmatter["completed_at"] = ""
        doc.frontmatter["updated_at"] = ts_dep_fail
        doc.body = append_progress_log(
            doc.body,
            f"{ts_dep_fail} job_complete: FAILED dependency gate; status=blocked; errors: {', '.join(dep_errors[:5])}",
        )
        write_md(plan_path, doc)
        if not args.no_sync:
            sync_project_plans(project_root, ts=ts_dep_fail)
        raise SystemExit("Job completion dependency gate failed:\n- " + "\n- ".join(dep_errors))

    # Bring global artifacts up to date before scoring.
    run_py("task_tracker_build.py", ["--project", str(project_root)])
    if not args.no_dashboard:
        run_py("dashboard_build.py", ["--project", str(project_root)])
    # Capture/refresh dependency snapshot before truth evaluation.
    run_py_best_effort("input_snapshot.py", ["--project", str(project_root), "--work-item-id", wi])

    ts_attempt = now_iso()
    doc = read_md(plan_path)
    doc.frontmatter["updated_at"] = ts_attempt
    doc.body = append_progress_log(doc.body, f"{ts_attempt} job_complete: attempting completion (prev_status={prev_status})")
    write_md(plan_path, doc)

    # Evaluate reward + truth while still non-done (no tentative done loophole).
    run_py("reward_eval.py", ["--project", str(project_root), "--no-sync", "--no-dashboard"])
    run_py("truth_eval.py", ["--project", str(project_root), "--no-sync", "--no-dashboard"])

    errors = gating_errors(project_root, job_dir)
    if errors:
        # Revert status to in_progress (do not claim done if gates fail).
        ts_fail = now_iso()
        doc = read_md(plan_path)
        fail_status = "blocked" if any(e.startswith("dependency gate") or "snapshot stale" in e for e in errors) else "in_progress"
        doc.frontmatter["status"] = fail_status if prev_status != "done" else prev_status
        doc.frontmatter["completed_at"] = ""
        doc.frontmatter["updated_at"] = ts_fail
        doc.body = append_progress_log(
            doc.body,
            f"{ts_fail} job_complete: FAILED gate; reverting to {doc.frontmatter['status']}; errors: {', '.join(errors[:5])}",
        )
        write_md(plan_path, doc)
        if not args.no_sync:
            sync_project_plans(project_root, ts=ts_fail)
        raise SystemExit("Job completion gate failed:\n- " + "\n- ".join(errors))

    # Gates passed; optionally cascade completion upward and then sync artifacts.
    ts_ok = now_iso()
    doc = read_md(plan_path)
    doc.frontmatter["status"] = "done"
    doc.frontmatter["completed_at"] = ts_ok
    doc.body = append_progress_log(doc.body, f"{ts_ok} job_complete: gate PASSED; status=done confirmed")
    doc.frontmatter["updated_at"] = ts_ok
    write_md(plan_path, doc)

    extra_promises: list[str] = []
    if args.cascade:
        ws_dir = parent_workstream_dir(project_root, job_dir)
        ws_id = try_complete_workstream(project_root, ws_dir, ts=ts_ok)
        if ws_id:
            extra_promises.append(f"<promise>{ws_id}-DONE</promise>")
        proj_id = try_complete_project(project_root, ts=ts_ok)
        if proj_id:
            extra_promises.append(f"<promise>{proj_id}-DONE</promise>")

    # Keep tracker/dashboard consistent with final status.
    run_py("task_tracker_build.py", ["--project", str(project_root)])

    run_py_best_effort(
        "invalidate_downstream.py",
        ["--project", str(project_root), "--upstream-work-item-id", wi, "--no-sync", "--no-dashboard"],
    )
    run_py_best_effort("orchestrate_plan.py", ["--project", str(project_root)])
    # Rebuild after invalidation because downstream statuses may have changed.
    run_py("task_tracker_build.py", ["--project", str(project_root)])
    if not args.no_sync:
        sync_project_plans(project_root, ts=ts_ok)
    if not args.no_dashboard:
        run_py("dashboard_build.py", ["--project", str(project_root)])

    if not args.no_open:
        run_py("dashboard_open.py", ["--project", str(project_root), "--once"])

    print(f"<promise>{wi}-DONE</promise>")
    for p in extra_promises:
        print(p)


if __name__ == "__main__":
    main()
