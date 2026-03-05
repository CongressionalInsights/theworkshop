#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
    parser.add_argument("--browser", choices=["default", "chrome", "safari"], default="default", help="Browser target")
    parser.add_argument("--force", action="store_true", help="Ignore open-once gating")
    parser.add_argument("--policy", choices=["always", "once", "manual"], default="", help="Override monitor policy")
    parser.add_argument("--no-open", action="store_true", help="Do not open dashboard")
    parser.add_argument("--no-watch", action="store_true", help="Do not start watcher")
    args = parser.parse_args(argv)

    project_root = resolve_project_root(args.project)

    rt_args = ["start", "--project", str(project_root)]
    if args.policy:
        rt_args += ["--policy", args.policy]
    if args.browser:
        rt_args += ["--browser", args.browser]
    if args.no_open:
        rt_args += ["--no-open"]
    if args.no_watch:
        rt_args += ["--no-watch"]
    if args.force:
        rt_args += ["--force-open"]
    run_py_best_effort("monitor_runtime.py", rt_args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
