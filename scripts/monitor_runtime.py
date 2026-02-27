#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
from pathlib import Path
from typing import Any

from tw_tools import run_script
from twlib import now_iso, read_md, resolve_project_root, write_md


def _state_path(project_root: Path) -> Path:
    return project_root / "tmp" / "monitor-runtime.json"


def _watch_pid_path(project_root: Path) -> Path:
    return project_root / "tmp" / "dashboard-watch.json"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    except Exception:
        return {}
    return {}


def _write_state(project_root: Path, payload: dict[str, Any]) -> None:
    path = _state_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _pid_alive(pid: int) -> bool:
    if pid <= 1:
        return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _session_id() -> str:
    for key in ("TERM_SESSION_ID", "ITERM_SESSION_ID", "THEWORKSHOP_SESSION_ID", "CODEX_THREAD_ID"):
        value = str(os.environ.get(key) or "").strip()
        if value:
            return value
    return "unknown"


def _project_policy(project_root: Path) -> str:
    doc = read_md(project_root / "plan.md")
    policy = str(doc.frontmatter.get("monitor_open_policy") or "always").strip()
    if policy not in {"always", "once", "manual"}:
        policy = "always"
    return policy


def _set_project_monitor_fields(project_root: Path, *, policy: str, session_id: str) -> None:
    plan_path = project_root / "plan.md"
    doc = read_md(plan_path)
    changed = False
    if str(doc.frontmatter.get("monitor_open_policy") or "").strip() != policy:
        doc.frontmatter["monitor_open_policy"] = policy
        changed = True
    if str(doc.frontmatter.get("monitor_session_id") or "").strip() != session_id:
        doc.frontmatter["monitor_session_id"] = session_id
        changed = True
    if changed:
        doc.frontmatter["updated_at"] = now_iso()
        write_md(plan_path, doc)


def _watch_pid(project_root: Path) -> int:
    payload = _load_json(_watch_pid_path(project_root))
    try:
        return int(payload.get("pid") or 0)
    except Exception:
        return 0


def start_monitor(project_root: Path, *, policy_override: str, no_open: bool, no_watch: bool, force_open: bool) -> dict[str, Any]:
    ts = now_iso()
    policy = policy_override or _project_policy(project_root)
    if policy not in {"always", "once", "manual"}:
        policy = "always"

    session_id = _session_id()
    _set_project_monitor_fields(project_root, policy=policy, session_id=session_id)

    disabled_open = str(os.environ.get("THEWORKSHOP_NO_OPEN") or "").strip() == "1"
    disabled_monitor = str(os.environ.get("THEWORKSHOP_NO_MONITOR") or "").strip() == "1"

    open_result = {"attempted": False, "ok": False, "message": "not attempted"}
    watch_result = {"attempted": False, "ok": False, "message": "not attempted"}

    should_open = (not no_open) and (policy != "manual") and (not disabled_open)
    if should_open:
        open_args = ["--project", str(project_root)]
        if policy == "always" or force_open:
            open_args += ["--force"]
        else:
            open_args += ["--once"]
        open_result["attempted"] = True
        try:
            run_script("dashboard_open.py", open_args, check=True)
        except Exception as exc:
            open_result["ok"] = False
            open_result["message"] = str(exc)
    else:
        if disabled_open:
            open_result["message"] = "disabled by THEWORKSHOP_NO_OPEN=1"
        elif policy == "manual":
            open_result["message"] = "policy=manual"
        elif no_open:
            open_result["message"] = "disabled by --no-open"

    should_watch = (not no_watch) and (not disabled_monitor)
    if should_watch:
        watch_result["attempted"] = True
        try:
            run_script(
                "dashboard_watch.py",
                ["--project", str(project_root), "--detach"],
                check=True,
            )
            watch_result["ok"] = True
            watch_result["message"] = "started"
        except Exception as exc:
            watch_result["ok"] = False
            watch_result["message"] = str(exc)
    else:
        if disabled_monitor:
            watch_result["message"] = "disabled by THEWORKSHOP_NO_MONITOR=1"
        elif no_watch:
            watch_result["message"] = "disabled by --no-watch"

    pid = _watch_pid(project_root)
    alive = _pid_alive(pid)

    runtime_warnings: list[str] = []
    if open_result["attempted"] and not open_result["ok"]:
        runtime_warnings.append("dashboard open failed")
    if watch_result["attempted"] and not watch_result["ok"]:
        runtime_warnings.append("dashboard watcher start failed")
    if watch_result["attempted"] and watch_result["ok"] and not alive:
        runtime_warnings.append("dashboard watcher not alive after start")

    status = "idle"
    if disabled_open and disabled_monitor:
        status = "disabled"
    elif runtime_warnings:
        status = "warning"
    elif watch_result["attempted"] and watch_result["ok"] and alive:
        status = "running"
    elif open_result["attempted"] and open_result["ok"]:
        status = "opened"

    state = {
        "schema": "theworkshop.monitor-runtime.v1",
        "status": status,
        "policy": policy,
        "session_id": session_id,
        "watch_pid": pid,
        "watch_alive": alive,
        "open_attempted": bool(open_result["attempted"]),
        "open_ok": bool(open_result["ok"]),
        "watch_attempted": bool(watch_result["attempted"]),
        "watch_ok": bool(watch_result["ok"]),
        "open_message": str(open_result.get("message") or ""),
        "watch_message": str(watch_result.get("message") or ""),
        "warnings": runtime_warnings,
        "updated_at": ts,
        "source": "monitor_runtime.start",
    }
    _write_state(project_root, state)
    return state


def stop_monitor(project_root: Path) -> dict[str, Any]:
    ts = now_iso()
    pid = _watch_pid(project_root)
    stopped = False
    if _pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
            stopped = True
        except Exception:
            stopped = False

    pid_path = _watch_pid_path(project_root)
    try:
        if pid_path.exists():
            pid_path.unlink()
    except Exception:
        pass

    state = {
        "schema": "theworkshop.monitor-runtime.v1",
        "status": "stopped",
        "policy": _project_policy(project_root),
        "session_id": _session_id(),
        "watch_pid": pid,
        "watch_alive": False,
        "stopped": stopped,
        "updated_at": ts,
        "source": "monitor_runtime.stop",
    }
    _write_state(project_root, state)
    return state


def monitor_status(project_root: Path) -> dict[str, Any]:
    state = _load_json(_state_path(project_root))
    if not state:
        state = {
            "schema": "theworkshop.monitor-runtime.v1",
            "status": "unknown",
            "policy": _project_policy(project_root),
            "session_id": _session_id(),
            "updated_at": "",
            "source": "monitor_runtime.status",
        }
    pid = _watch_pid(project_root)
    state["watch_pid"] = pid
    state["watch_alive"] = _pid_alive(pid)
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description="TheWorkshop monitor runtime controller.")
    parser.add_argument("action", choices=["start", "stop", "status"])
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--policy", choices=["always", "once", "manual"], default="")
    parser.add_argument("--no-open", action="store_true", help="Do not open dashboard window")
    parser.add_argument("--no-watch", action="store_true", help="Do not start dashboard watcher")
    parser.add_argument("--force-open", action="store_true", help="Force browser open even in once mode")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    if args.action == "start":
        payload = start_monitor(
            project_root,
            policy_override=args.policy,
            no_open=args.no_open,
            no_watch=args.no_watch,
            force_open=args.force_open,
        )
    elif args.action == "stop":
        payload = stop_monitor(project_root)
    else:
        payload = monitor_status(project_root)

    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
