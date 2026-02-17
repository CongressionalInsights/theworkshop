#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from twlib import now_iso, read_md, resolve_project_root


def _pid_alive(pid: int) -> bool:
    if pid <= 1:
        return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _read_pidfile(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_pidfile(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _project_status(project_root: Path) -> str:
    try:
        doc = read_md(project_root / "plan.md")
        return str(doc.frontmatter.get("status") or "").strip()
    except Exception:
        return ""


def _max_mtime(paths: list[Path]) -> float:
    best = 0.0
    for p in paths:
        try:
            st = p.stat()
            best = max(best, float(st.st_mtime))
        except Exception:
            continue
    return best


def watched_paths(project_root: Path) -> list[Path]:
    paths: list[Path] = []
    # Core control-plane docs
    paths.append(project_root / "plan.md")
    paths.append(project_root / "workstreams" / "index.md")

    # Workstreams + jobs plans
    paths.extend(sorted(project_root.glob("workstreams/WS-*/plan.md")))
    paths.extend(sorted(project_root.glob("workstreams/WS-*/jobs/WI-*/plan.md")))

    # Logs/outputs that influence dashboard numbers
    paths.append(project_root / "logs" / "execution.jsonl")
    paths.append(project_root / "outputs" / "rewards.json")
    paths.extend(sorted(project_root.glob("outputs/*-task-tracker.csv")))
    paths.append(project_root / "notes" / "github-map.json")
    paths.append(project_root / "notes" / "lessons-index.json")
    return paths


def run_dashboard_build(project_root: Path) -> tuple[int, str]:
    scripts_dir = Path(__file__).resolve().parent
    cmd = [sys.executable, str(scripts_dir / "dashboard_build.py"), "--project", str(project_root)]
    proc = subprocess.run(cmd, text=True, capture_output=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    return int(proc.returncode), out.strip()


def detach_self(project_root: Path, args: argparse.Namespace, *, pid_file: Path, log_file: Path) -> int:
    if pid_file.exists():
        st = _read_pidfile(pid_file)
        pid = int(st.get("pid") or 0)
        if _pid_alive(pid):
            return 0

    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--project",
        str(project_root),
        "--interval",
        str(args.interval),
        "--pid-file",
        str(pid_file),
        "--log-file",
        str(log_file),
        "--max-seconds",
        str(args.max_seconds),
    ]

    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as fh:
        fh.write(f"{now_iso()} dashboard_watch: detaching: {' '.join(cmd)}\n")
    out = log_file.open("a", encoding="utf-8")
    try:
        subprocess.Popen(
            cmd,
            stdout=out,
            stderr=out,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except Exception as e:
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(f"{now_iso()} dashboard_watch: detach failed: {e}\n")
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Watch a TheWorkshop project and rebuild dashboard artifacts on change.")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--interval", type=float, default=5.0, help="Poll interval seconds (default: 5)")
    parser.add_argument(
        "--max-seconds",
        type=int,
        default=8 * 60 * 60,
        help="Maximum runtime in seconds before exiting (default: 28800 = 8h; 0 = unlimited).",
    )
    parser.add_argument("--detach", action="store_true", help="Start watcher in background and exit immediately.")
    parser.add_argument("--pid-file", default="", help="PID file path (default: <project>/tmp/dashboard-watch.json)")
    parser.add_argument("--log-file", default="", help="Log file path for detach mode (default: <project>/tmp/dashboard-watch.log)")
    args = parser.parse_args(argv)

    # Opt-out for CI/tests/headless. If the user doesn't want a browser, they usually
    # don't want background monitor processes either.
    if str(os.environ.get("THEWORKSHOP_NO_MONITOR") or "").strip() == "1":
        return 0
    if str(os.environ.get("THEWORKSHOP_NO_OPEN") or "").strip() == "1":
        return 0

    project_root = resolve_project_root(args.project)

    pid_file = Path(args.pid_file).expanduser() if args.pid_file else (project_root / "tmp" / "dashboard-watch.json")
    if not pid_file.is_absolute():
        pid_file = (project_root / pid_file).resolve()
    log_file = Path(args.log_file).expanduser() if args.log_file else (project_root / "tmp" / "dashboard-watch.log")
    if not log_file.is_absolute():
        log_file = (project_root / log_file).resolve()

    if args.detach:
        # Best-effort background start; the caller can ignore failures.
        return detach_self(project_root, args, pid_file=pid_file, log_file=log_file)

    # Single-instance guard.
    if pid_file.exists():
        st = _read_pidfile(pid_file)
        pid = int(st.get("pid") or 0)
        if _pid_alive(pid):
            return 0

    _write_pidfile(
        pid_file,
        {
            "schema": "theworkshop.monitor.v1",
            "kind": "dashboard_watch",
            "pid": os.getpid(),
            "started_at": now_iso(),
            "interval_sec": float(args.interval),
            "max_seconds": int(args.max_seconds),
            "project": str(project_root),
        },
    )

    start = time.time()
    last_mtime = 0.0
    last_build_at = 0.0

    # First build so the browser has something fresh quickly.
    rc, out = run_dashboard_build(project_root)
    last_build_at = time.time()
    if rc != 0:
        print(f"{now_iso()} dashboard_watch: initial build failed (best-effort): {out}", file=sys.stderr)

    while True:
        if args.max_seconds and args.max_seconds > 0 and (time.time() - start) > float(args.max_seconds):
            break

        status = _project_status(project_root)
        if status in {"done", "cancelled"}:
            break

        cur_mtime = _max_mtime(watched_paths(project_root))
        if cur_mtime > last_mtime:
            last_mtime = cur_mtime
            rc, out = run_dashboard_build(project_root)
            last_build_at = time.time()
            if rc != 0:
                print(f"{now_iso()} dashboard_watch: build failed (best-effort): {out}", file=sys.stderr)

        # Safety valve: if nothing changes for a long while, still rebuild occasionally so
        # estimated tokens / elapsed-like fields don't feel frozen forever.
        if (time.time() - last_build_at) > 60.0:
            rc, out = run_dashboard_build(project_root)
            last_build_at = time.time()
            if rc != 0:
                print(f"{now_iso()} dashboard_watch: periodic build failed (best-effort): {out}", file=sys.stderr)

        time.sleep(max(0.25, float(args.interval)))

    try:
        pid_file.unlink(missing_ok=True)  # type: ignore[arg-type]
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
