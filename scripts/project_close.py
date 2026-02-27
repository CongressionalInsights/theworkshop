#!/usr/bin/env python3
from __future__ import annotations

import argparse

from transition import transition_entity
from twlib import resolve_project_root


def main() -> None:
    parser = argparse.ArgumentParser(description="Close a TheWorkshop project as done or cancelled.")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--status", choices=["done", "cancelled"], default="cancelled")
    parser.add_argument("--reason", required=True, help="Closure reason")
    parser.add_argument("--actor", default="project_close.py")
    parser.add_argument("--no-sync", action="store_true")
    parser.add_argument("--no-dashboard", action="store_true")
    parser.add_argument("--no-monitor", action="store_true")
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    res = transition_entity(
        project_root,
        entity_kind="project",
        entity_id=None,
        to_status=args.status,
        reason=args.reason,
        actor=args.actor,
        cascade=(args.status == "cancelled"),
        sync=not args.no_sync,
        refresh_dashboard=not args.no_dashboard,
        start_monitor=not args.no_monitor,
        no_open=args.no_open,
    )
    if res.promise:
        print(res.promise)


if __name__ == "__main__":
    main()
