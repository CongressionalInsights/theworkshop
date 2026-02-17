#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from plan_sync import sync_project_plans
from twlib import list_job_dirs, list_workstream_dirs, now_iso, read_md, resolve_project_root, write_md


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


def find_workstream_dir(project_root: Path, ws_id: str) -> Path:
    for ws_dir in list_workstream_dirs(project_root):
        if ws_dir.name.startswith(ws_id):
            return ws_dir
    raise SystemExit(f"Workstream not found: {ws_id}")


def try_complete_project(project_root: Path, *, ts: str) -> str | None:
    proj_plan = project_root / "plan.md"
    if not proj_plan.exists():
        return None
    proj_doc = read_md(proj_plan)
    proj_id = str(proj_doc.frontmatter.get("id") or "").strip()
    status = str(proj_doc.frontmatter.get("status") or "planned").strip()
    if status in {"done", "cancelled"}:
        return None

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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Complete a TheWorkshop workstream (only if all jobs are done). Updates status/timestamps and syncs marker tables."
    )
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--workstream-id", required=True, help="WS-... to complete")
    parser.add_argument(
        "--cascade",
        action="store_true",
        help="If completion succeeds, auto-complete the project when it becomes eligible (all workstreams done).",
    )
    parser.add_argument("--no-sync", action="store_true", help="Do not run plan_sync after completion")
    parser.add_argument("--no-dashboard", action="store_true", help="Skip dashboard build (not recommended)")
    parser.add_argument("--no-open", action="store_true", help="Do not auto-open the dashboard (best-effort)")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    ws_id = args.workstream_id.strip()
    ws_dir = find_workstream_dir(project_root, ws_id)

    # Agreement gate: execution requires agreement_status=agreed.
    proj = read_md(project_root / "plan.md")
    agree = str(proj.frontmatter.get("agreement_status") or "").strip()
    if agree != "agreed":
        raise SystemExit("agreement_status must be 'agreed' before workstream completion (set it in project plan frontmatter).")

    # Verify all jobs are done.
    not_done = []
    for job_dir in list_job_dirs(ws_dir):
        doc = read_md(job_dir / "plan.md")
        wi = str(doc.frontmatter.get("work_item_id") or "").strip()
        st = str(doc.frontmatter.get("status") or "planned").strip()
        if st != "done":
            not_done.append(f"{wi or job_dir.name} ({st})")

    if not_done:
        raise SystemExit("Cannot complete workstream; jobs not done:\n- " + "\n- ".join(not_done))

    ts = now_iso()
    ws_plan = ws_dir / "plan.md"
    ws_doc = read_md(ws_plan)
    ws_doc.frontmatter["status"] = "done"
    ws_doc.frontmatter["completed_at"] = ts
    ws_doc.frontmatter["updated_at"] = ts
    ws_doc.body = append_progress_log(ws_doc.body, f"{ts} workstream_complete: all jobs done; status=done")
    write_md(ws_plan, ws_doc)

    proj_promise = ""
    if args.cascade:
        proj_id = try_complete_project(project_root, ts=ts)
        if proj_id:
            proj_promise = f"<promise>{proj_id}-DONE</promise>"

    if not args.no_sync:
        sync_project_plans(project_root, ts=ts)

    if not args.no_dashboard:
        run_py("dashboard_build.py", ["--project", str(project_root)])
    if not args.no_open:
        run_py("dashboard_open.py", ["--project", str(project_root), "--once"])

    print(f"<promise>{ws_id}-DONE</promise>")
    if proj_promise:
        print(proj_promise)


if __name__ == "__main__":
    main()
