#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import monitor_runtime
from twlib import resolve_project_root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Open TheWorkshop dashboard via monitor runtime (best-effort, open-once).")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--path", default="outputs/dashboard.html", help="Compatibility-only dashboard path argument")
    parser.add_argument(
        "--once",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Open only once per project per session (default: true). Use --no-once to disable gating.",
    )
    parser.add_argument("--force", action="store_true", help="Ignore open-once gating")
    parser.add_argument("--browser", choices=["default", "chrome", "safari"], default="default", help="Browser target")
    parser.add_argument("--dry-run", action="store_true", help="Print what would happen; do not open")
    parser.add_argument(
        "--state-file",
        default="",
        help="Compatibility-only state-file argument; monitor runtime now owns dashboard state.",
    )
    args = parser.parse_args(argv)

    project_root = resolve_project_root(args.project)
    dashboard_path = Path(args.path).expanduser()
    if not dashboard_path.is_absolute():
        dashboard_path = (project_root / dashboard_path).resolve()

    if args.dry_run:
        ok, message = monitor_runtime._ensure_dashboard(project_root)  # noqa: SLF001
        print(str(dashboard_path))
        if ok:
            print(dashboard_path.as_uri())
            return 0
        raise SystemExit(message)

    payload = monitor_runtime.open_dashboard(
        project_root,
        browser=args.browser,
        once=bool(args.once),
        force=bool(args.force),
        dry_run=False,
    )
    print(str(dashboard_path))
    print(str(payload.get("server_url") or dashboard_path.as_uri()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
