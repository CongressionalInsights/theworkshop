#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from twlib import resolve_project_root


def run_py_best_effort(script: str, argv: list[str]) -> int:
    scripts_dir = Path(__file__).resolve().parent
    cmd = [sys.executable, str(scripts_dir / script)] + argv
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True)
    except Exception as e:
        print(f"warning: failed to run {script} (best-effort): {e}", file=sys.stderr)
        return 0
    if proc.returncode != 0:
        # Best-effort: monitoring should never be a hard error for the skill.
        msg = (proc.stdout or "") + (proc.stderr or "")
        msg = msg.strip()
        if msg:
            print(f"warning: {script} failed (best-effort): {msg}", file=sys.stderr)
        return 0
    if proc.stdout:
        print(proc.stdout, end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Open + keep TheWorkshop dashboard live (best-effort).")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--interval", type=float, default=5.0, help="Watcher poll interval seconds (default: 5)")
    parser.add_argument("--max-seconds", type=int, default=8 * 60 * 60, help="Watcher max runtime seconds (default: 8h)")
    parser.add_argument("--browser", choices=["default", "chrome", "safari"], default="default", help="Browser target")
    parser.add_argument("--force", action="store_true", help="Ignore open-once gating")
    args = parser.parse_args(argv)

    # Respect opt-outs.
    if str(os.environ.get("THEWORKSHOP_NO_OPEN") or "").strip() == "1":
        return 0
    if str(os.environ.get("THEWORKSHOP_NO_MONITOR") or "").strip() == "1":
        return 0

    project_root = resolve_project_root(args.project)

    open_argv = ["--project", str(project_root), "--once", "--browser", args.browser]
    if args.force:
        open_argv += ["--force"]
    run_py_best_effort("dashboard_open.py", open_argv)

    watch_argv = [
        "--project",
        str(project_root),
        "--detach",
        "--interval",
        str(args.interval),
        "--max-seconds",
        str(args.max_seconds),
    ]
    run_py_best_effort("dashboard_watch.py", watch_argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

