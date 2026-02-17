#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from plan_sync import sync_project_plans
from twlib import normalize_str_list, now_iso, read_md, resolve_project_root, write_md


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


def append_decision_log(body: str, line: str) -> str:
    heading = "# Decisions"
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


def dependency_statuses(project_root: Path, wi_ids: list[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for dep in wi_ids:
        matches = list(project_root.glob(f"workstreams/WS-*/jobs/{dep}-*/plan.md"))
        if len(matches) != 1:
            out.append((dep, "missing"))
            continue
        dep_doc = read_md(matches[0])
        dep_status = str(dep_doc.frontmatter.get("status") or "planned").strip()
        out.append((dep, dep_status))
    return out


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
    except Exception as e:
        # Monitoring should never block core execution.
        print(f"warning: {script} failed (best-effort): {e}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="Start a TheWorkshop job (set status, timestamps, iteration, sync tables).")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--work-item-id", required=True, help="WI-... to start")
    parser.add_argument("--no-sync", action="store_true", help="Do not run plan_sync after updating the job")
    parser.add_argument("--no-dashboard", action="store_true", help="Skip dashboard build at execution start")
    parser.add_argument("--no-open", action="store_true", help="Do not auto-open the dashboard (best-effort)")
    parser.add_argument("--no-monitor", action="store_true", help="Do not start the background dashboard watcher (best-effort)")
    parser.add_argument(
        "--allow-unmet-deps",
        action="store_true",
        help="Allow starting even when depends_on jobs are not done (requires --decision-note).",
    )
    parser.add_argument(
        "--decision-note",
        default="",
        help="Required with --allow-unmet-deps; logged in project Decisions.",
    )
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    wi = args.work_item_id.strip()
    job_dir = find_job_dir(project_root, wi)
    plan_path = job_dir / "plan.md"

    ts = now_iso()

    # Agreement gate: execution requires agreement_status=agreed.
    proj = read_md(project_root / "plan.md")
    agree = str(proj.frontmatter.get("agreement_status") or "").strip()
    if agree != "agreed":
        raise SystemExit("agreement_status must be 'agreed' before job start (set it in project plan frontmatter).")
    proj_status = str(proj.frontmatter.get("status") or "planned").strip()
    if proj_status in {"done", "cancelled"}:
        raise SystemExit(f"Cannot start job while project status={proj_status!r}")

    ws_dir = parent_workstream_dir(project_root, job_dir)
    ws_doc = read_md(ws_dir / "plan.md")
    ws_id = str(ws_doc.frontmatter.get("id") or ws_dir.name).strip()
    ws_status = str(ws_doc.frontmatter.get("status") or "planned").strip()
    if ws_status in {"done", "cancelled"}:
        raise SystemExit(f"Cannot start job while parent workstream {ws_id} status={ws_status!r}")

    doc = read_md(plan_path)
    prev_status = str(doc.frontmatter.get("status") or "planned").strip()
    if prev_status in {"done", "cancelled"}:
        raise SystemExit(f"Cannot start job in status={prev_status!r}: {wi}")

    deps = normalize_str_list(doc.frontmatter.get("depends_on"))
    dep_states = dependency_statuses(project_root, deps)
    unmet = [f"{dep}={state}" for dep, state in dep_states if state != "done"]
    if unmet and not args.allow_unmet_deps:
        raise SystemExit(
            "Cannot start job while dependencies are not done: "
            + ", ".join(unmet)
            + ". Resolve dependencies first, or use --allow-unmet-deps with --decision-note."
        )
    if unmet and args.allow_unmet_deps:
        if not str(args.decision_note or "").strip():
            raise SystemExit("--allow-unmet-deps requires --decision-note so the exception is explicitly recorded.")
        proj_doc = read_md(project_root / "plan.md")
        decision = (
            f"{ts}: dependency override for {wi}; unmet dependencies: {', '.join(unmet)}; "
            f"note: {args.decision_note.strip()}"
        )
        proj_doc.body = append_decision_log(proj_doc.body, decision)
        proj_doc.frontmatter["updated_at"] = ts
        write_md(project_root / "plan.md", proj_doc)
        doc.body = append_progress_log(doc.body, f"{ts} dependency_override: {', '.join(unmet)}; note: {args.decision_note.strip()}")

    # Transition -> in_progress and stamp times.
    doc.frontmatter["status"] = "in_progress"
    if not str(doc.frontmatter.get("started_at") or "").strip():
        doc.frontmatter["started_at"] = ts

    # Iteration is the attempt counter (Ralph-loop friendly).
    try:
        iteration = int(doc.frontmatter.get("iteration") or 0)
    except Exception:
        iteration = 0
    if prev_status != "in_progress":
        if iteration <= 0:
            iteration = 1
        elif prev_status in {"planned", "blocked"}:
            iteration += 1
    doc.frontmatter["iteration"] = iteration
    doc.frontmatter["updated_at"] = ts
    doc.body = append_progress_log(doc.body, f"{ts} job_start: {prev_status} -> in_progress (iteration {iteration})")
    write_md(plan_path, doc)

    if not args.no_sync:
        sync_project_plans(project_root, ts=ts)
    run_py_best_effort("orchestrate_plan.py", ["--project", str(project_root)])

    # Monitoring (best-effort): keep the dashboard current and open it once execution begins.
    if not args.no_dashboard:
        run_py("dashboard_build.py", ["--project", str(project_root)])
    if not args.no_open:
        run_py("dashboard_open.py", ["--project", str(project_root), "--once"])
    if not args.no_monitor:
        run_py_best_effort("dashboard_watch.py", ["--project", str(project_root), "--detach"])

    print(wi)


if __name__ == "__main__":
    main()
