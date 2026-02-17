#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import webbrowser
from pathlib import Path

from twlib import now_iso, resolve_project_root


def _session_id() -> str:
    # Prefer explicit session ids when provided; fall back to stable-ish process parent.
    for k in ("THEWORKSHOP_SESSION_ID", "CODEX_THREAD_ID", "TERM_SESSION_ID", "ITERM_SESSION_ID"):
        v = str(os.environ.get(k) or "").strip()
        if v:
            return v
    try:
        return f"ppid:{os.getppid()}"
    except Exception:
        return "unknown"


def _run_py(script: str, argv: list[str]) -> subprocess.CompletedProcess[str]:
    scripts_dir = Path(__file__).resolve().parent
    cmd = [sys.executable, str(scripts_dir / script)] + argv
    return subprocess.run(cmd, text=True, capture_output=True)


def _ensure_dashboard(project_root: Path, dashboard_path: Path, *, out_html_override: bool) -> None:
    if dashboard_path.exists():
        return
    argv = ["--project", str(project_root)]
    if out_html_override:
        argv += ["--out-html", str(dashboard_path)]
    proc = _run_py("dashboard_build.py", argv)
    if proc.returncode != 0:
        raise SystemExit(
            "dashboard_build.py failed:\n"
            f"  exit={proc.returncode}\n"
            f"  stdout:\n{proc.stdout}\n"
            f"  stderr:\n{proc.stderr}\n"
        )


def _load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_state(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _open_url(url: str, *, browser: str) -> bool:
    # Best-effort: default to Python webbrowser.
    if browser == "default":
        try:
            return bool(webbrowser.open_new(url))
        except Exception:
            return False

    # Browser overrides are macOS-best-effort; fall back to webbrowser otherwise.
    if sys.platform == "darwin":
        try:
            if browser == "chrome":
                proc = subprocess.run(
                    ["open", "-na", "Google Chrome", "--args", "--new-window", url],
                    text=True,
                    capture_output=True,
                )
                if proc.returncode == 0:
                    return True
            elif browser == "safari":
                proc = subprocess.run(["open", "-a", "Safari", url], text=True, capture_output=True)
                if proc.returncode == 0:
                    return True
        except Exception:
            pass

    try:
        return bool(webbrowser.open_new(url))
    except Exception:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Open TheWorkshop dashboard in a browser window (best-effort, open-once).")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--path", default="outputs/dashboard.html", help="Dashboard path (default: outputs/dashboard.html)")
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
        help="State file for open-once gating (default: <project>/tmp/dashboard-open.json)",
    )
    args = parser.parse_args(argv)

    project_root = resolve_project_root(args.project)

    dashboard_path = Path(args.path).expanduser()
    if not dashboard_path.is_absolute():
        dashboard_path = project_root / dashboard_path
    dashboard_path = dashboard_path.resolve()

    state_file = Path(args.state_file).expanduser() if args.state_file else (project_root / "tmp" / "dashboard-open.json")
    if not state_file.is_absolute():
        state_file = (project_root / state_file).resolve()

    # Ensure dashboard exists (build if missing).
    out_html_override = (args.path or "") not in {"", "outputs/dashboard.html"}
    _ensure_dashboard(project_root, dashboard_path, out_html_override=out_html_override)

    url = dashboard_path.as_uri()
    print(str(dashboard_path))
    print(url)

    # Opt-out for CI/tests/headless.
    if str(os.environ.get("THEWORKSHOP_NO_OPEN") or "").strip() == "1":
        return 0
    if args.dry_run:
        return 0

    sid = _session_id()
    if args.once and not args.force and state_file.exists():
        st = _load_state(state_file)
        if (
            str(st.get("schema") or "") == "theworkshop.monitor.v1"
            and bool(st.get("opened"))
            and str(st.get("session_id") or "") == sid
        ):
            return 0

    ok = _open_url(url, browser=args.browser)
    if ok:
        _write_state(
            state_file,
            {
                "schema": "theworkshop.monitor.v1",
                "opened": True,
                "opened_at": now_iso(),
                "session_id": sid,
                "browser": args.browser,
                "url": url,
                "path": str(dashboard_path),
            },
        )
    else:
        # Best-effort: do not fail lifecycle scripts if opening isn't possible.
        print("warning: could not open dashboard in a browser window (best-effort).", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

