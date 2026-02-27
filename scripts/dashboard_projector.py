#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import dashboard_build
from twlib import now_iso, read_md, resolve_project_root


@contextmanager
def _lock_file(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as fp:
        fcntl.flock(fp.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fp.fileno(), fcntl.LOCK_UN)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(str(tmp_path), str(path))
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass


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


def _monitor_state(project_root: Path) -> dict[str, Any]:
    state_path = project_root / "tmp" / "monitor-runtime.json"
    pid_path = project_root / "tmp" / "dashboard-watch.json"

    state = _load_json(state_path)
    pid_state = _load_json(pid_path)
    pid = int(pid_state.get("pid") or state.get("watch_pid") or 0)
    alive = False
    if pid > 1:
        try:
            os.kill(pid, 0)
            alive = True
        except Exception:
            alive = False

    if not state:
        proj = read_md(project_root / "plan.md")
        policy = str(proj.frontmatter.get("monitor_open_policy") or "always").strip()
        state = {
            "schema": "theworkshop.monitor-runtime.v1",
            "status": "unknown",
            "policy": policy if policy in {"always", "once", "manual"} else "always",
            "watch_pid": pid,
            "watch_alive": alive,
            "updated_at": "",
            "source": "derived",
        }
    else:
        state = dict(state)
        state["watch_pid"] = pid
        state["watch_alive"] = alive
    return state


def _collect_projection_warnings(project_root: Path, monitor_state: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    status = str(monitor_state.get("status") or "unknown")
    policy = str(monitor_state.get("policy") or "always")
    project_status = str(read_md(project_root / "plan.md").frontmatter.get("status") or "planned").strip()
    terminal_project = project_status in {"done", "cancelled"}

    if str(os.environ.get("THEWORKSHOP_NO_OPEN") or "").strip() == "1":
        warnings.append("dashboard open disabled by THEWORKSHOP_NO_OPEN=1")
    if str(os.environ.get("THEWORKSHOP_NO_MONITOR") or "").strip() == "1":
        warnings.append("dashboard monitor disabled by THEWORKSHOP_NO_MONITOR=1")

    if (not terminal_project) and policy != "manual" and status in {"unknown", "stopped", "error"}:
        warnings.append("monitor runtime is not active while policy requires automatic monitoring")

    if (not terminal_project) and policy != "manual" and not bool(monitor_state.get("watch_alive")):
        warnings.append("dashboard watcher is not running")

    events_path = project_root / "logs" / "events.jsonl"
    if not events_path.exists():
        warnings.append("transition events log missing: logs/events.jsonl")

    return warnings


def _next_projection_seq(project_root: Path) -> tuple[int, Path]:
    state_path = project_root / "tmp" / "dashboard-projector-state.json"
    st = _load_json(state_path)
    seq = int(st.get("projection_seq") or 0) + 1
    return seq, state_path


def main() -> None:
    parser = argparse.ArgumentParser(description="TheWorkshop dashboard projector (single-writer, lock + atomic writes).")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--out-json", help="Output JSON path (default: outputs/dashboard.json)")
    parser.add_argument("--out-md", help="Output Markdown path (default: outputs/dashboard.md)")
    parser.add_argument("--out-html", help="Output HTML path (default: outputs/dashboard.html)")
    parser.add_argument("--warning", action="append", default=[], help="Projection warning to append")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    out_dir = project_root / "outputs"
    out_json = Path(args.out_json).expanduser().resolve() if args.out_json else out_dir / "dashboard.json"
    out_md = Path(args.out_md).expanduser().resolve() if args.out_md else out_dir / "dashboard.md"
    out_html = Path(args.out_html).expanduser().resolve() if args.out_html else out_dir / "dashboard.html"

    lock_path = project_root / "tmp" / "dashboard-projector.lock"

    with _lock_file(lock_path):
        payload = dashboard_build.build_payload(project_root)
        monitor_state = _monitor_state(project_root)
        projection_seq, state_path = _next_projection_seq(project_root)
        warnings = _collect_projection_warnings(project_root, monitor_state)
        for w in args.warning:
            s = str(w).strip()
            if s:
                warnings.append(s)

        payload["projection_seq"] = projection_seq
        payload["projection_warnings"] = warnings
        payload["monitor_state"] = monitor_state

        _atomic_write_text(out_json, json.dumps(payload, indent=2) + "\n")
        _atomic_write_text(out_md, dashboard_build.render_md(payload))
        _atomic_write_text(out_html, dashboard_build.render_html(payload))

        state_payload = {
            "schema": "theworkshop.projector.v1",
            "projection_seq": projection_seq,
            "generated_at": payload.get("generated_at") or now_iso(),
            "project": str(project_root),
            "out_json": str(out_json),
            "out_md": str(out_md),
            "out_html": str(out_html),
            "warnings": warnings,
        }
        _atomic_write_text(state_path, json.dumps(state_payload, indent=2) + "\n")

    print(str(out_html))


if __name__ == "__main__":
    main()
