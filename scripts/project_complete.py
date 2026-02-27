#!/usr/bin/env python3
from __future__ import annotations

import argparse

from transition import transition_entity
from twlib import read_md, resolve_project_root


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Complete a TheWorkshop project (canonical transition engine, all workstreams must be done)."
    )
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--no-sync", action="store_true", help="Do not run plan_sync after completion")
    parser.add_argument("--no-dashboard", action="store_true", help="Skip dashboard projection")
    parser.add_argument("--no-open", action="store_true", help="Do not open dashboard")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)

    proj = read_md(project_root / "plan.md")
    agree = str(proj.frontmatter.get("agreement_status") or "").strip()
    if agree != "agreed":
        raise SystemExit("agreement_status must be 'agreed' before project completion (set it in project plan frontmatter).")

    res = transition_entity(
        project_root,
        entity_kind="project",
        entity_id=None,
        to_status="done",
        reason="project completion command",
        actor="project_complete.py",
        sync=not args.no_sync,
        refresh_dashboard=not args.no_dashboard,
        start_monitor=(not args.no_open),
        no_open=args.no_open,
    )

    if res.promise:
        print(res.promise)


if __name__ == "__main__":
    main()
