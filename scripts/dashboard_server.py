#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from twlib import now_iso, resolve_project_root


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, host: str, port: int, project_root: Path, interval_sec: float) -> None:
        self.project_root = project_root
        self.outputs_dir = project_root / "outputs"
        self.dashboard_json = self.outputs_dir / "dashboard.json"
        self.dashboard_html = self.outputs_dir / "dashboard.html"
        self.interval_sec = max(0.5, float(interval_sec))
        super().__init__((host, port), DashboardHandler)

    @property
    def url(self) -> str:
        host, port = self.server_address
        return f"http://{host}:{port}/"


class DashboardHandler(SimpleHTTPRequestHandler):
    server: DashboardServer

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        return

    def translate_path(self, path: str) -> str:
        parsed = urlparse(path)
        rel = parsed.path.lstrip("/")
        if rel == "" or rel == "dashboard" or rel == "index.html":
            rel = "dashboard.html"
        resolved = (self.server.outputs_dir / rel).resolve()
        if resolved != self.server.outputs_dir and self.server.outputs_dir not in resolved.parents:
            return str(self.server.outputs_dir / "__not_found__")
        return str(resolved)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/events":
            self._handle_sse()
            return
        if parsed.path == "/api/dashboard":
            self._handle_dashboard_json()
            return
        if parsed.path in {"/", "/dashboard", "/index.html"} and not self.server.dashboard_html.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "dashboard.html missing; run `theworkshop dashboard`")
            return
        super().do_GET()

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def _handle_dashboard_json(self) -> None:
        if not self.server.dashboard_json.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "dashboard.json missing")
            return
        body = self.server.dashboard_json.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_sse(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        last_sig = ""
        try:
            while True:
                payload = self._build_update_payload()
                sig = json.dumps(payload, sort_keys=True)
                if sig != last_sig:
                    last_sig = sig
                    self.wfile.write(f"data: {sig}\n\n".encode("utf-8"))
                    self.wfile.flush()
                else:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                time.sleep(self.server.interval_sec)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return

    def _build_update_payload(self) -> dict:
        generated_at = ""
        mtime = 0.0
        if self.server.dashboard_json.exists():
            try:
                mtime = float(self.server.dashboard_json.stat().st_mtime)
            except Exception:
                mtime = 0.0
            try:
                payload = json.loads(self.server.dashboard_json.read_text(encoding="utf-8"))
                generated_at = str(payload.get("generated_at") or "") if isinstance(payload, dict) else ""
            except Exception:
                generated_at = ""
        return {
            "generated_at": generated_at,
            "dashboard_mtime": mtime,
            "dashboard_json": str(self.server.dashboard_json),
        }


def _best_effort_open(url: str) -> None:
    import webbrowser

    try:
        webbrowser.open_new(url)
    except Exception:
        pass


def _state_path(project_root: Path, state_file: str = "") -> Path:
    if state_file:
        path = Path(state_file).expanduser()
        return path if path.is_absolute() else (project_root / path).resolve()
    return project_root / "tmp" / "dashboard-server.json"


def _log_path(project_root: Path, log_file: str = "") -> Path:
    if log_file:
        path = Path(log_file).expanduser()
        return path if path.is_absolute() else (project_root / path).resolve()
    return project_root / "tmp" / "dashboard-server.log"


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _pid_alive(pid: int) -> bool:
    if pid <= 1:
        return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _persist_state(
    project_root: Path,
    url: str,
    *,
    host: str,
    port: int,
    pid: int,
    status: str,
    state_path: Path,
) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "theworkshop.dashboard-server.v1",
        "status": status,
        "url": url,
        "host": host,
        "port": int(port),
        "pid": int(pid),
        "project": str(project_root),
        "updated_at": now_iso(),
    }
    state_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _detach_self(project_root: Path, args: argparse.Namespace, *, state_path: Path, log_path: Path) -> int:
    state = _load_json(state_path)
    pid = int(state.get("pid") or 0)
    if _pid_alive(pid) and str(state.get("url") or "").strip():
        return 0

    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--project",
        str(project_root),
        "--host",
        args.host,
        "--port",
        str(int(args.port)),
        "--interval-sec",
        str(float(args.interval_sec)),
        "--state-file",
        str(state_path),
        "--log-file",
        str(log_path),
    ]
    if args.open:
        cmd.append("--open")

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(f"{now_iso()} dashboard_server: detaching: {' '.join(cmd)}\n")

    out = log_path.open("a", encoding="utf-8")
    try:
        subprocess.Popen(
            cmd,
            stdout=out,
            stderr=out,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except Exception as exc:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"{now_iso()} dashboard_server: detach failed: {exc}\n")
        return 2
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve TheWorkshop dashboard with optional SSE live updates.")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--interval-sec", type=float, default=1.0, help="SSE polling interval for dashboard.json")
    parser.add_argument("--open", action="store_true", help="Open dashboard URL in browser")
    parser.add_argument("--detach", action="store_true", help="Start server in background and exit immediately")
    parser.add_argument("--state-file", default="", help="State file path (default: <project>/tmp/dashboard-server.json)")
    parser.add_argument("--log-file", default="", help="Log file for detach mode (default: <project>/tmp/dashboard-server.log)")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    state_path = _state_path(project_root, args.state_file)
    log_path = _log_path(project_root, args.log_file)

    if args.detach:
        raise SystemExit(_detach_self(project_root, args, state_path=state_path, log_path=log_path))

    existing = _load_json(state_path)
    existing_pid = int(existing.get("pid") or 0)
    existing_url = str(existing.get("url") or "").strip()
    if _pid_alive(existing_pid) and existing_url:
        print(existing_url, flush=True)
        return

    server = DashboardServer(args.host, int(args.port), project_root, float(args.interval_sec))

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    host, port = server.server_address
    _persist_state(project_root, server.url, host=str(host), port=int(port), pid=os.getpid(), status="running", state_path=state_path)
    print(server.url, flush=True)

    if args.open:
        _best_effort_open(server.url)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.shutdown()
    finally:
        _persist_state(project_root, server.url, host=str(host), port=int(port), pid=0, status="stopped", state_path=state_path)


if __name__ == "__main__":
    main()
