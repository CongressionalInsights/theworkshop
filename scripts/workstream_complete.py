#!/usr/bin/env python3
from __future__ import annotations

import argparse

from transition import transition_entity
from twlib import list_workstream_dirs, read_md, resolve_project_root


def all_workstreams_done(project_root):
    for ws_dir in list_workstream_dirs(project_root):
        ws_doc = read_md(ws_dir / "plan.md")
        ws_status = str(ws_doc.frontmatter.get("status") or "planned").strip()
        if ws_status != "done":
            return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Complete a TheWorkshop workstream (canonical transition engine)."
    )
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--workstream-id", required=True, help="WS-... to complete")
    parser.add_argument("--cascade", action="store_true", help="Cascade project completion when eligible")
    parser.add_argument("--no-sync", action="store_true", help="Skip plan sync")
    parser.add_argument("--no-dashboard", action="store_true", help="Skip dashboard projection")
    parser.add_argument("--no-open", action="store_true", help="Do not open dashboard")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)

    proj = read_md(project_root / "plan.md")
    agree = str(proj.frontmatter.get("agreement_status") or "").strip()
    if agree != "agreed":
        raise SystemExit("agreement_status must be 'agreed' before workstream completion (set it in project plan frontmatter).")

    ws_res = transition_entity(
        project_root,
        entity_kind="workstream",
        entity_id=args.workstream_id.strip(),
        to_status="done",
        reason="workstream completion command",
        actor="workstream_complete.py",
        sync=not args.no_sync,
        refresh_dashboard=not args.no_dashboard,
        start_monitor=(not args.no_open),
        no_open=args.no_open,
    )

    proj_promise = ""
    if args.cascade:
        proj_status = str(read_md(project_root / "plan.md").frontmatter.get("status") or "planned").strip()
        if proj_status not in {"done", "cancelled"} and all_workstreams_done(project_root):
            pj_res = transition_entity(
                project_root,
                entity_kind="project",
                entity_id=None,
                to_status="done",
                reason="cascade after workstream completion",
                actor="workstream_complete.py",
                sync=not args.no_sync,
                refresh_dashboard=not args.no_dashboard,
                start_monitor=False,
            )
            proj_promise = pj_res.promise

    if ws_res.promise:
        print(ws_res.promise)
    if proj_promise:
        print(proj_promise)


if __name__ == "__main__":
    main()
