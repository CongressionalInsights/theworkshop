#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any

from tw_tools import run_script
from twlib import now_iso, read_md, resolve_project_root, write_md


STATE_SCHEMA = "theworkshop.monitor-runtime.v2"
TERMINAL_STATUSES = {"done", "cancelled"}


def _state_path(project_root: Path) -> Path:
    return project_root / "tmp" / "monitor-runtime.json"


def _watch_pid_path(project_root: Path) -> Path:
    return project_root / "tmp" / "dashboard-watch.json"


def _server_state_path(project_root: Path) -> Path:
    return project_root / "tmp" / "dashboard-server.json"


def _runner_state_path(project_root: Path) -> Path:
    return project_root / "tmp" / "workflow-runner.json"


def _dashboard_html_path(project_root: Path) -> Path:
    return project_root / "outputs" / "dashboard.html"


def _dashboard_json_path(project_root: Path) -> Path:
    return project_root / "outputs" / "dashboard.json"


def _legacy_open_state_path(project_root: Path) -> Path:
    return project_root / "tmp" / "dashboard-open.json"


def _transient_paths(project_root: Path) -> list[Path]:
    return [
        _legacy_open_state_path(project_root),
        _watch_pid_path(project_root),
        project_root / "tmp" / "dashboard-watch.log",
        _server_state_path(project_root),
        project_root / "tmp" / "dashboard-server.log",
        _runner_state_path(project_root),
        project_root / "tmp" / "workflow-runner.log",
        project_root / "tmp" / "dashboard-projector.lock",
    ]


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


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


def _project_status(project_root: Path) -> str:
    doc = read_md(project_root / "plan.md")
    return str(doc.frontmatter.get("status") or "planned").strip()


def _project_policy(project_root: Path) -> str:
    doc = read_md(project_root / "plan.md")
    policy = str(doc.frontmatter.get("monitor_open_policy") or "once").strip()
    if policy not in {"always", "once", "manual"}:
        policy = "once"
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


def _ensure_dashboard(project_root: Path) -> tuple[bool, str]:
    html_path = _dashboard_html_path(project_root)
    json_path = _dashboard_json_path(project_root)
    if html_path.exists() and json_path.exists():
        return True, "dashboard ready"
    result = run_script("dashboard_projector.py", ["--project", str(project_root)], check=False)
    if result.returncode != 0:
        return False, ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    if not html_path.exists():
        return False, "dashboard projector did not produce outputs/dashboard.html"
    return True, "dashboard built"


def _open_url(url: str, *, browser: str) -> bool:
    if browser == "default":
        try:
            return bool(webbrowser.open_new(url))
        except Exception:
            return False

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


def _runtime_snapshot(project_root: Path) -> dict[str, Any]:
    persisted = _load_json(_state_path(project_root))
    server_state = _load_json(_server_state_path(project_root))
    watch_state = _load_json(_watch_pid_path(project_root))
    runner_state = _load_json(_runner_state_path(project_root))
    legacy_open = _load_json(_legacy_open_state_path(project_root))

    watch_pid = _int_value(watch_state.get("pid") or persisted.get("watch_pid"))
    server_pid = _int_value(server_state.get("pid") or persisted.get("server_pid"))
    runner_pid = _int_value(runner_state.get("pid") or persisted.get("runner_pid"))

    watch_alive = _pid_alive(watch_pid)
    server_alive = _pid_alive(server_pid)
    runner_alive = _pid_alive(runner_pid)

    open_count = _int_value(persisted.get("open_count"))
    if open_count <= 0 and bool(legacy_open.get("opened")):
        open_count = 1

    state = {
        "schema": STATE_SCHEMA,
        "status": str(persisted.get("status") or "unknown"),
        "policy": str(persisted.get("policy") or _project_policy(project_root)),
        "session_id": str(persisted.get("session_id") or _session_id()),
        "project_status": _project_status(project_root),
        "dashboard_path": str(_dashboard_html_path(project_root)),
        "server_url": str(server_state.get("url") or persisted.get("server_url") or ""),
        "server_pid": server_pid,
        "server_alive": server_alive,
        "watch_pid": watch_pid,
        "watch_alive": watch_alive,
        "runner_pid": runner_pid,
        "runner_alive": runner_alive,
        "open_count": open_count,
        "open_session_id": str(
            persisted.get("open_session_id") or legacy_open.get("session_id") or ""
        ),
        "open_opened_at": str(
            persisted.get("open_opened_at") or legacy_open.get("opened_at") or ""
        ),
        "open_target": str(persisted.get("open_target") or legacy_open.get("url") or ""),
        "open_message": str(persisted.get("open_message") or ""),
        "open_ok": bool(persisted.get("open_ok")),
        "open_attempted": bool(persisted.get("open_attempted")),
        "watch_ok": bool(persisted.get("watch_ok")),
        "watch_attempted": bool(persisted.get("watch_attempted")),
        "watch_message": str(persisted.get("watch_message") or ""),
        "server_ok": bool(persisted.get("server_ok")),
        "server_attempted": bool(persisted.get("server_attempted")),
        "server_message": str(persisted.get("server_message") or ""),
        "cleanup_status": str(persisted.get("cleanup_status") or "none"),
        "last_cleanup_at": str(persisted.get("last_cleanup_at") or ""),
        "cleanup_removed": list(persisted.get("cleanup_removed") or []),
        "cleanup_stopped": list(persisted.get("cleanup_stopped") or []),
        "cleanup_errors": list(persisted.get("cleanup_errors") or []),
        "updated_at": str(persisted.get("updated_at") or ""),
        "source": str(persisted.get("source") or "monitor_runtime.status"),
    }
    if state["policy"] not in {"always", "once", "manual"}:
        state["policy"] = "once"
    return state


def _write_state(project_root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    snapshot = _runtime_snapshot(project_root)
    snapshot.update(payload)
    snapshot["schema"] = STATE_SCHEMA
    snapshot["updated_at"] = now_iso()
    _write_json(_state_path(project_root), snapshot)
    return snapshot


def _wait_for_json(path: Path, *, timeout_sec: float = 4.0) -> dict[str, Any]:
    deadline = time.time() + max(0.25, timeout_sec)
    latest: dict[str, Any] = {}
    while time.time() < deadline:
        latest = _load_json(path)
        if latest:
            return latest
        time.sleep(0.1)
    return latest


def _ensure_server(project_root: Path) -> dict[str, Any]:
    state = _runtime_snapshot(project_root)
    url = str(state.get("server_url") or "").strip()
    if state.get("server_alive") and url:
        return {
            "attempted": False,
            "ok": True,
            "message": "reused existing server",
            "pid": _int_value(state.get("server_pid")),
            "alive": True,
            "url": url,
        }

    ok, message = _ensure_dashboard(project_root)
    if not ok:
        return {"attempted": False, "ok": False, "message": message, "pid": 0, "alive": False, "url": ""}

    result = run_script("dashboard_server.py", ["--project", str(project_root), "--detach"], check=False)
    if result.returncode != 0:
        return {
            "attempted": True,
            "ok": False,
            "message": ((result.stdout or "") + "\n" + (result.stderr or "")).strip(),
            "pid": 0,
            "alive": False,
            "url": "",
        }

    server_state = _wait_for_json(_server_state_path(project_root))
    pid = _int_value(server_state.get("pid"))
    url = str(server_state.get("url") or "").strip()
    alive = _pid_alive(pid)
    if not alive or not url:
        return {
            "attempted": True,
            "ok": False,
            "message": "dashboard server did not become healthy",
            "pid": pid,
            "alive": alive,
            "url": url,
        }
    return {
        "attempted": True,
        "ok": True,
        "message": "server ready",
        "pid": pid,
        "alive": alive,
        "url": url,
    }


def _ensure_watcher(project_root: Path) -> dict[str, Any]:
    state = _runtime_snapshot(project_root)
    if state.get("watch_alive"):
        return {
            "attempted": False,
            "ok": True,
            "message": "reused existing watcher",
            "pid": _int_value(state.get("watch_pid")),
            "alive": True,
        }

    result = run_script(
        "dashboard_watch.py",
        ["--project", str(project_root), "--detach"],
        check=False,
    )
    if result.returncode != 0:
        return {
            "attempted": True,
            "ok": False,
            "message": ((result.stdout or "") + "\n" + (result.stderr or "")).strip(),
            "pid": 0,
            "alive": False,
        }

    watch_state = _wait_for_json(_watch_pid_path(project_root))
    pid = _int_value(watch_state.get("pid"))
    alive = _pid_alive(pid)
    if not alive:
        return {
            "attempted": True,
            "ok": False,
            "message": "dashboard watcher did not become healthy",
            "pid": pid,
            "alive": False,
        }
    return {
        "attempted": True,
        "ok": True,
        "message": "watcher ready",
        "pid": pid,
        "alive": True,
    }


def _should_open_for_policy(
    policy: str,
    state: dict[str, Any],
    *,
    session_id: str,
    force_open: bool,
    manual_ok: bool,
    once: bool,
) -> tuple[bool, str]:
    if force_open:
        return True, "force open"
    if policy == "manual" and not manual_ok:
        return False, "policy=manual"
    if not once:
        return True, "open without once gating"
    open_session_id = str(state.get("open_session_id") or "").strip()
    if open_session_id and open_session_id == session_id:
        return False, "already opened in this session"
    if policy == "always":
        return True, "policy=always"
    return True, "policy=once"


def _maybe_open_dashboard(
    project_root: Path,
    state: dict[str, Any],
    *,
    policy: str,
    browser: str,
    force_open: bool,
    manual_ok: bool,
    once: bool,
) -> dict[str, Any]:
    session_id = _session_id()
    url = str(state.get("server_url") or "").strip()
    if not url:
        return {
            "attempted": False,
            "ok": False,
            "message": "dashboard URL unavailable",
            "target": "",
        }

    should_open, reason = _should_open_for_policy(
        policy,
        state,
        session_id=session_id,
        force_open=force_open,
        manual_ok=manual_ok,
        once=once,
    )
    if not should_open:
        return {
            "attempted": False,
            "ok": bool(state.get("open_ok")),
            "message": reason,
            "target": url,
        }

    ok = _open_url(url, browser=browser)
    next_count = _int_value(state.get("open_count")) + (1 if ok else 0)
    payload = {
        "open_attempted": True,
        "open_ok": ok,
        "open_message": "opened" if ok else "could not open dashboard URL",
        "open_target": url,
        "open_session_id": session_id if ok else str(state.get("open_session_id") or ""),
        "open_opened_at": now_iso() if ok else str(state.get("open_opened_at") or ""),
        "open_count": next_count if ok else _int_value(state.get("open_count")),
    }
    _write_state(project_root, payload)
    return {
        "attempted": True,
        "ok": ok,
        "message": payload["open_message"],
        "target": url,
    }


def start_monitor(
    project_root: Path,
    *,
    policy_override: str,
    no_open: bool,
    no_watch: bool,
    force_open: bool,
    browser: str = "default",
) -> dict[str, Any]:
    ts = now_iso()
    policy = policy_override or _project_policy(project_root)
    if policy not in {"always", "once", "manual"}:
        policy = "once"

    session_id = _session_id()
    _set_project_monitor_fields(project_root, policy=policy, session_id=session_id)

    disabled_open = str(os.environ.get("THEWORKSHOP_NO_OPEN") or "").strip() == "1"
    disabled_monitor = str(os.environ.get("THEWORKSHOP_NO_MONITOR") or "").strip() == "1"
    project_status = _project_status(project_root)
    terminal_project = project_status in TERMINAL_STATUSES

    state = _runtime_snapshot(project_root)
    state.update(
        {
            "policy": policy,
            "session_id": session_id,
            "project_status": project_status,
            "source": "monitor_runtime.start",
        }
    )

    server_result = {"attempted": False, "ok": False, "message": "not attempted", "pid": 0, "alive": False, "url": ""}
    watch_result = {"attempted": False, "ok": False, "message": "not attempted", "pid": 0, "alive": False}
    open_result = {"attempted": False, "ok": False, "message": "not attempted", "target": ""}

    should_watch = (not terminal_project) and (not no_watch) and (not disabled_monitor)
    should_server = should_watch or (not no_open and not disabled_open) or force_open
    if terminal_project and not force_open and no_open:
        should_server = False

    if should_server:
        server_result = _ensure_server(project_root)
        state.update(
            {
                "server_attempted": bool(server_result["attempted"]),
                "server_ok": bool(server_result["ok"]),
                "server_message": str(server_result["message"] or ""),
                "server_pid": _int_value(server_result.get("pid")),
                "server_alive": bool(server_result.get("alive")),
                "server_url": str(server_result.get("url") or ""),
            }
        )
        _write_state(project_root, state)
    else:
        if terminal_project:
            server_result["message"] = "project is terminal"
        elif disabled_open and disabled_monitor:
            server_result["message"] = "open + monitor disabled by env"
        elif no_open:
            server_result["message"] = "disabled by --no-open"

    if should_watch:
        watch_result = _ensure_watcher(project_root)
        state.update(
            {
                "watch_attempted": bool(watch_result["attempted"]),
                "watch_ok": bool(watch_result["ok"]),
                "watch_message": str(watch_result["message"] or ""),
                "watch_pid": _int_value(watch_result.get("pid")),
                "watch_alive": bool(watch_result.get("alive")),
            }
        )
        _write_state(project_root, state)
    else:
        if disabled_monitor:
            watch_result["message"] = "disabled by THEWORKSHOP_NO_MONITOR=1"
        elif no_watch:
            watch_result["message"] = "disabled by --no-watch"
        elif terminal_project:
            watch_result["message"] = "project is terminal"

    state = _runtime_snapshot(project_root)
    if (not terminal_project) and (not no_open) and (not disabled_open):
        open_result = _maybe_open_dashboard(
            project_root,
            state,
            policy=policy,
            browser=browser,
            force_open=force_open,
            manual_ok=False,
            once=(policy != "always"),
        )
    else:
        if disabled_open:
            open_result["message"] = "disabled by THEWORKSHOP_NO_OPEN=1"
        elif no_open:
            open_result["message"] = "disabled by --no-open"
        elif terminal_project:
            open_result["message"] = "project is terminal"

    state = _runtime_snapshot(project_root)
    warnings: list[str] = []
    if server_result["attempted"] and not server_result["ok"]:
        warnings.append("dashboard server unavailable")
    if watch_result["attempted"] and not watch_result["ok"]:
        warnings.append("dashboard watcher unavailable")
    if open_result["attempted"] and not open_result["ok"]:
        warnings.append("dashboard open failed")

    if disabled_open and disabled_monitor:
        status = "disabled"
    elif terminal_project and not state.get("watch_alive") and not state.get("server_alive"):
        status = "terminal"
    elif warnings:
        status = "warning"
    elif state.get("watch_alive"):
        status = "running"
    elif state.get("server_alive") and state.get("open_ok"):
        status = "opened"
    elif state.get("server_alive"):
        status = "serving"
    else:
        status = "idle"

    return _write_state(
        project_root,
        {
            "status": status,
            "policy": policy,
            "session_id": session_id,
            "project_status": project_status,
            "server_attempted": bool(server_result["attempted"]),
            "server_ok": bool(server_result["ok"]),
            "server_message": str(server_result["message"] or ""),
            "watch_attempted": bool(watch_result["attempted"]),
            "watch_ok": bool(watch_result["ok"]),
            "watch_message": str(watch_result["message"] or ""),
            "open_attempted": bool(open_result["attempted"]),
            "open_ok": bool(open_result["ok"]),
            "open_message": str(open_result["message"] or ""),
            "open_target": str(open_result.get("target") or state.get("open_target") or ""),
            "cleanup_status": "none",
            "cleanup_removed": [],
            "cleanup_stopped": [],
            "cleanup_errors": [],
            "last_cleanup_at": "",
            "warnings": warnings,
            "updated_at": ts,
            "source": "monitor_runtime.start",
        },
    )


def open_dashboard(
    project_root: Path,
    *,
    browser: str = "default",
    once: bool = True,
    force: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    state = _runtime_snapshot(project_root)
    policy = _project_policy(project_root)
    if dry_run:
        ok, message = _ensure_dashboard(project_root)
        return _write_state(
            project_root,
            {
                "policy": policy,
                "session_id": _session_id(),
                "project_status": _project_status(project_root),
                "open_attempted": False,
                "open_ok": False,
                "open_message": message if ok else f"dry-run: {message}",
                "source": "monitor_runtime.open",
            },
        )

    server_result = _ensure_server(project_root)
    state.update(
        {
            "policy": policy,
            "session_id": _session_id(),
            "project_status": _project_status(project_root),
            "server_attempted": bool(server_result["attempted"]),
            "server_ok": bool(server_result["ok"]),
            "server_message": str(server_result["message"] or ""),
            "server_pid": _int_value(server_result.get("pid")),
            "server_alive": bool(server_result.get("alive")),
            "server_url": str(server_result.get("url") or ""),
            "source": "monitor_runtime.open",
        }
    )
    _write_state(project_root, state)
    if not server_result["ok"]:
        return _write_state(
            project_root,
            {
                "status": "warning",
                "open_attempted": False,
                "open_ok": False,
                "open_message": str(server_result["message"] or ""),
                "source": "monitor_runtime.open",
            },
        )

    open_result = _maybe_open_dashboard(
        project_root,
        _runtime_snapshot(project_root),
        policy=policy,
        browser=browser,
        force_open=force,
        manual_ok=True,
        once=once,
    )
    state = _runtime_snapshot(project_root)
    status = "opened" if open_result["ok"] else "serving" if state.get("server_alive") else "warning"
    return _write_state(
        project_root,
        {
            "status": status,
            "policy": policy,
            "session_id": _session_id(),
            "open_attempted": bool(open_result["attempted"]),
            "open_ok": bool(open_result["ok"]),
            "open_message": str(open_result["message"] or ""),
            "open_target": str(open_result.get("target") or state.get("open_target") or ""),
            "source": "monitor_runtime.open",
        },
    )


def _terminate_pid(pid: int, *, label: str, timeout_sec: float = 2.0) -> tuple[bool, str]:
    if not _pid_alive(pid):
        return False, f"{label} not running"
    try:
        os.kill(pid, signal.SIGTERM)
    except Exception as exc:
        return False, f"{label} SIGTERM failed: {exc}"
    deadline = time.time() + max(0.25, timeout_sec)
    while time.time() < deadline:
        if not _pid_alive(pid):
            return True, f"{label} stopped"
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except Exception as exc:
        return False, f"{label} SIGKILL failed: {exc}"
    return (not _pid_alive(pid), f"{label} killed")


def stop_monitor(project_root: Path, *, cleanup: bool = True, reason: str = "", terminal_status: str = "") -> dict[str, Any]:
    ts = now_iso()
    state = _runtime_snapshot(project_root)
    stopped: list[str] = []
    errors: list[str] = []

    for label, pid in (
        ("dashboard watcher", _int_value(state.get("watch_pid"))),
        ("dashboard server", _int_value(state.get("server_pid"))),
        ("workflow runner", _int_value(state.get("runner_pid"))),
    ):
        ok, message = _terminate_pid(pid, label=label)
        if ok:
            stopped.append(message)
        elif "not running" not in message:
            errors.append(message)

    removed: list[str] = []
    if cleanup:
        for path in _transient_paths(project_root):
            try:
                if path.exists():
                    path.unlink()
                    removed.append(str(path.relative_to(project_root)))
            except Exception as exc:
                errors.append(f"remove {path.name}: {exc}")

    status = "terminal" if terminal_status in TERMINAL_STATUSES else "stopped"
    cleanup_status = "pruned" if cleanup and not errors else "partial" if cleanup else "none"
    return _write_state(
        project_root,
        {
            "status": status,
            "policy": _project_policy(project_root),
            "session_id": _session_id(),
            "project_status": _project_status(project_root),
            "server_pid": 0,
            "server_alive": False,
            "server_ok": False,
            "server_attempted": False,
            "server_message": "stopped",
            "server_url": "",
            "watch_pid": 0,
            "watch_alive": False,
            "watch_ok": False,
            "watch_attempted": False,
            "watch_message": "stopped",
            "runner_pid": 0,
            "runner_alive": False,
            "open_attempted": False,
            "open_ok": False,
            "open_message": "stopped",
            "cleanup_status": cleanup_status,
            "last_cleanup_at": ts,
            "cleanup_removed": removed,
            "cleanup_stopped": stopped,
            "cleanup_errors": errors,
            "stop_reason": reason,
            "updated_at": ts,
            "source": "monitor_runtime.stop",
        },
    )


def monitor_status(project_root: Path) -> dict[str, Any]:
    state = _runtime_snapshot(project_root)
    warnings: list[str] = []
    if state.get("server_pid") and not state.get("server_alive"):
        warnings.append("dashboard server pid is stale")
    if state.get("watch_pid") and not state.get("watch_alive"):
        warnings.append("dashboard watcher pid is stale")
    if state.get("runner_pid") and not state.get("runner_alive"):
        warnings.append("workflow runner pid is stale")

    status = str(state.get("status") or "unknown")
    if state.get("project_status") in TERMINAL_STATUSES and not state.get("watch_alive") and not state.get("server_alive"):
        status = "terminal" if str(state.get("cleanup_status") or "") != "none" else "stopped"
    elif warnings:
        status = "warning"
    elif state.get("watch_alive"):
        status = "running"
    elif state.get("server_alive") and state.get("open_ok"):
        status = "opened"
    elif state.get("server_alive"):
        status = "serving"
    elif str(state.get("cleanup_status") or "") != "none":
        status = "stopped"
    elif str(state.get("open_message") or "").strip():
        status = "idle"

    return _write_state(
        project_root,
        {
            "status": status,
            "policy": _project_policy(project_root),
            "session_id": _session_id(),
            "project_status": _project_status(project_root),
            "warnings": warnings,
            "source": "monitor_runtime.status",
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="TheWorkshop monitor runtime controller.")
    parser.add_argument("action", choices=["start", "stop", "status"])
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--policy", choices=["always", "once", "manual"], default="")
    parser.add_argument("--no-open", action="store_true", help="Do not open dashboard window")
    parser.add_argument("--no-watch", action="store_true", help="Do not start dashboard watcher")
    parser.add_argument("--force-open", action="store_true", help="Force browser open even in once/manual mode")
    parser.add_argument("--browser", choices=["default", "chrome", "safari"], default="default")
    parser.add_argument("--no-cleanup", action="store_true", help="Do not prune transient runtime files on stop")
    parser.add_argument("--reason", default="", help="Optional stop reason for runtime state")
    parser.add_argument("--terminal-status", choices=["done", "cancelled"], default="")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    if args.action == "start":
        payload = start_monitor(
            project_root,
            policy_override=args.policy,
            no_open=args.no_open,
            no_watch=args.no_watch,
            force_open=args.force_open,
            browser=args.browser,
        )
    elif args.action == "stop":
        payload = stop_monitor(
            project_root,
            cleanup=not args.no_cleanup,
            reason=args.reason,
            terminal_status=args.terminal_status,
        )
    else:
        payload = monitor_status(project_root)

    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
