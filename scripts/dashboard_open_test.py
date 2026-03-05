#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import tempfile
import webbrowser
from pathlib import Path

# Import from scripts/ so we can call dashboard_open.main(...) directly.
SCRIPTS_DIR = Path(__file__).resolve().parent
import sys  # noqa: E402

sys.path.insert(0, str(SCRIPTS_DIR))

import dashboard_open  # noqa: E402
import monitor_runtime  # noqa: E402


def write_min_project(root: Path) -> None:
    (root / "outputs").mkdir(parents=True, exist_ok=True)
    (root / "tmp").mkdir(parents=True, exist_ok=True)
    (root / "plan.md").write_text(
        "\n".join(
            [
                "---",
                "kind: project",
                "id: PJ-TEST-000",
                "title: Dashboard Open Test",
                "status: in_progress",
                "agreement_status: agreed",
                "---",
                "",
                "# Test Project",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (root / "outputs" / "dashboard.html").write_text("<!doctype html><html><body>ok</body></html>\n", encoding="utf-8")
    (root / "outputs" / "dashboard.json").write_text('{"schema":"theworkshop.dashboard.v1"}\n', encoding="utf-8")


def main() -> None:
    calls = {"n": 0}
    orig_open_new = webbrowser.open_new

    def stub_open_new(url: str) -> bool:
        calls["n"] += 1
        return True

    with tempfile.TemporaryDirectory(prefix="theworkshop-dashboard-open-") as td:
        project_root = Path(td).resolve()
        write_min_project(project_root)

        runtime_state = project_root / "tmp" / "monitor-runtime.json"
        legacy_state = project_root / "tmp" / "dashboard-open.json"

        os.environ["THEWORKSHOP_SESSION_ID"] = "session-test-1"

        webbrowser.open_new = stub_open_new
        try:
            # --dry-run should not open and should not create state.
            rc = dashboard_open.main(["--project", str(project_root), "--dry-run"])
            if rc != 0:
                raise RuntimeError(f"dry-run expected rc=0, got {rc}")
            if calls["n"] != 0:
                raise RuntimeError(f"dry-run should not open browser, calls={calls['n']}")
            if runtime_state.exists():
                raise RuntimeError("dry-run should not create runtime state")

            # First open should call browser once, start/reuse server, and write runtime state.
            rc = dashboard_open.main(["--project", str(project_root)])
            if rc != 0:
                raise RuntimeError(f"first open expected rc=0, got {rc}")
            if calls["n"] != 1:
                raise RuntimeError(f"expected 1 open call, got {calls['n']}")
            if not runtime_state.exists():
                raise RuntimeError("expected monitor-runtime.json to be created on open")
            first = json.loads(runtime_state.read_text(encoding="utf-8"))
            first_url = str(first.get("server_url") or "").strip()
            first_pid = int(first.get("server_pid") or 0)
            if not first_url.startswith("http://"):
                raise RuntimeError(f"expected live server url, got {first}")
            if first_pid <= 1:
                raise RuntimeError(f"expected dashboard server pid, got {first}")
            if int(first.get("open_count") or 0) != 1:
                raise RuntimeError(f"expected open_count=1, got {first}")
            if legacy_state.exists():
                raise RuntimeError("dashboard_open compatibility shim should not recreate dashboard-open.json")

            # Second open in same session should be gated by --once.
            rc = dashboard_open.main(["--project", str(project_root)])
            if rc != 0:
                raise RuntimeError(f"second open expected rc=0, got {rc}")
            if calls["n"] != 1:
                raise RuntimeError(f"expected gated open to not call browser again, got {calls['n']}")
            second = json.loads(runtime_state.read_text(encoding="utf-8"))
            if str(second.get("server_url") or "").strip() != first_url:
                raise RuntimeError(f"expected server reuse, got {second}")
            if int(second.get("server_pid") or 0) != first_pid:
                raise RuntimeError(f"expected server pid reuse, got {second}")
            if int(second.get("open_count") or 0) != 1:
                raise RuntimeError(f"expected open_count to remain 1, got {second}")

            # --force bypasses gating.
            rc = dashboard_open.main(["--project", str(project_root), "--force"])
            if rc != 0:
                raise RuntimeError(f"force open expected rc=0, got {rc}")
            if calls["n"] != 2:
                raise RuntimeError(f"expected force open to call browser again, got {calls['n']}")
            forced = json.loads(runtime_state.read_text(encoding="utf-8"))
            if int(forced.get("open_count") or 0) != 2:
                raise RuntimeError(f"expected open_count=2 after force open, got {forced}")
        finally:
            try:
                monitor_runtime.stop_monitor(project_root)
            except Exception:
                pass
            webbrowser.open_new = orig_open_new

    print("DASHBOARD OPEN TEST PASSED")


if __name__ == "__main__":
    main()
