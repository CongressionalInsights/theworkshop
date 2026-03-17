#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent


def py(script: str) -> list[str]:
    return [sys.executable, str(SCRIPTS_DIR / script)]


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["THEWORKSHOP_NO_OPEN"] = "1"
    env["THEWORKSHOP_NO_MONITOR"] = "1"
    env["THEWORKSHOP_NO_KEYCHAIN"] = "1"
    proc = subprocess.run(cmd, text=True, capture_output=True, env=env)
    if check and proc.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            f"  cmd={' '.join(cmd)}\n"
            f"  exit={proc.returncode}\n"
            f"  stdout:\n{proc.stdout}\n"
            f"  stderr:\n{proc.stderr}\n"
        )
    return proc


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="theworkshop-dash-server-") as td:
        base = Path(td).resolve()
        project_root = Path(
            run(py("project_new.py") + ["--name", "Dashboard Server Test", "--base-dir", str(base)]).stdout.strip()
        ).resolve()
        run(py("dashboard_build.py") + ["--project", str(project_root)])

        env = dict(os.environ)
        env["THEWORKSHOP_NO_OPEN"] = "1"
        proc = subprocess.Popen(
            py("dashboard_server.py") + ["--project", str(project_root), "--host", "127.0.0.1", "--port", "0"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )

        try:
            state_path = project_root / "tmp" / "dashboard-server.json"
            url = ""
            start = time.time()
            while time.time() - start < 10:
                if proc.poll() is not None:
                    stderr = proc.stderr.read() if proc.stderr else ""
                    raise RuntimeError(f"dashboard_server exited early: rc={proc.returncode} stderr={stderr}")
                if state_path.exists():
                    payload = json.loads(state_path.read_text(encoding="utf-8"))
                    url = str(payload.get("url") or "").strip()
                    if url:
                        break
                time.sleep(0.1)

            if not url.startswith("http://"):
                raise RuntimeError(f"Invalid dashboard server URL output: {url!r}")

            with urllib.request.urlopen(url + "api/dashboard", timeout=5) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
            payload = json.loads(body)
            if payload.get("schema") != "theworkshop.dashboard.v1":
                raise RuntimeError("Unexpected dashboard payload schema")

            with urllib.request.urlopen(url + "events", timeout=5) as resp:
                data_line = resp.readline().decode("utf-8", errors="ignore").strip()
            if not data_line.startswith("data: "):
                raise RuntimeError(f"Expected first SSE line to start with data:, got {data_line!r}")
            event_payload = json.loads(data_line[len("data: ") :])
            if str(event_payload.get("generated_at") or "") != str(payload.get("generated_at") or ""):
                raise RuntimeError(f"Expected SSE generated_at to match dashboard payload: {event_payload}")
            for key in ("project_status", "monitor_status"):
                if key not in event_payload:
                    raise RuntimeError(f"Expected SSE payload to include {key!r}: {event_payload}")

        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

        print("DASHBOARD SERVER TEST PASSED")


if __name__ == "__main__":
    main()
