#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from plan_sync import sync_project_plans
from twlib import list_workstream_dirs, load_workstream, now_iso, read_md, resolve_project_root, write_md


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
        description="Complete a TheWorkshop project (only if all workstreams are done). Updates status/timestamps and syncs marker tables."
    )
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--no-sync", action="store_true", help="Do not run plan_sync after completion")
    parser.add_argument("--no-dashboard", action="store_true", help="Skip dashboard build (not recommended)")
    parser.add_argument("--no-open", action="store_true", help="Do not auto-open the dashboard (best-effort)")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)

    # Agreement gate: execution requires agreement_status=agreed.
    proj0 = read_md(project_root / "plan.md")
    agree = str(proj0.frontmatter.get("agreement_status") or "").strip()
    if agree != "agreed":
        raise SystemExit("agreement_status must be 'agreed' before project completion (set it in project plan frontmatter).")

    workstreams = [load_workstream(p) for p in list_workstream_dirs(project_root)]
    not_done = [f"{ws.id} ({ws.status})" for ws in workstreams if ws.status != "done"]
    if not_done:
        raise SystemExit("Cannot complete project; workstreams not done:\n- " + "\n- ".join(not_done))

    ts = now_iso()
    proj_plan = project_root / "plan.md"
    proj_doc = read_md(proj_plan)
    proj_id = str(proj_doc.frontmatter.get("id") or "").strip()
    proj_doc.frontmatter["status"] = "done"
    proj_doc.frontmatter["completed_at"] = ts
    proj_doc.frontmatter["updated_at"] = ts
    proj_doc.body = append_progress_log(proj_doc.body, f"{ts} project_complete: all workstreams done; status=done")
    write_md(proj_plan, proj_doc)

    if not args.no_sync:
        sync_project_plans(project_root, ts=ts)

    if not args.no_dashboard:
        run_py("dashboard_build.py", ["--project", str(project_root)])
    if not args.no_open:
        run_py("dashboard_open.py", ["--project", str(project_root), "--once"])

    if proj_id:
        print(f"<promise>{proj_id}-DONE</promise>")
    else:
        print("<promise>PROJECT-DONE</promise>")


if __name__ == "__main__":
    main()
