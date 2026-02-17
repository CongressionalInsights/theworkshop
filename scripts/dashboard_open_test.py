#!/usr/bin/env python3
from __future__ import annotations

import os
import tempfile
import webbrowser
from pathlib import Path

# Import from scripts/ so we can call dashboard_open.main(...) directly.
SCRIPTS_DIR = Path(__file__).resolve().parent
import sys  # noqa: E402

sys.path.insert(0, str(SCRIPTS_DIR))

import dashboard_open  # noqa: E402


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


def main() -> None:
    calls = {"n": 0}
    orig_open_new = webbrowser.open_new

    def stub_open_new(url: str) -> bool:
        calls["n"] += 1
        return True

    with tempfile.TemporaryDirectory(prefix="theworkshop-dashboard-open-") as td:
        project_root = Path(td).resolve()
        write_min_project(project_root)

        state_file = project_root / "tmp" / "dashboard-open.json"

        os.environ["THEWORKSHOP_SESSION_ID"] = "session-test-1"

        webbrowser.open_new = stub_open_new
        try:
            # --dry-run should not open and should not create state.
            rc = dashboard_open.main(["--project", str(project_root), "--dry-run", "--state-file", str(state_file)])
            if rc != 0:
                raise RuntimeError(f"dry-run expected rc=0, got {rc}")
            if calls["n"] != 0:
                raise RuntimeError(f"dry-run should not open browser, calls={calls['n']}")
            if state_file.exists():
                raise RuntimeError("dry-run should not create state file")

            # First open should call browser once and write state.
            rc = dashboard_open.main(["--project", str(project_root), "--state-file", str(state_file)])
            if rc != 0:
                raise RuntimeError(f"first open expected rc=0, got {rc}")
            if calls["n"] != 1:
                raise RuntimeError(f"expected 1 open call, got {calls['n']}")
            if not state_file.exists():
                raise RuntimeError("expected state file to be created on open")

            # Second open in same session should be gated by --once.
            rc = dashboard_open.main(["--project", str(project_root), "--state-file", str(state_file)])
            if rc != 0:
                raise RuntimeError(f"second open expected rc=0, got {rc}")
            if calls["n"] != 1:
                raise RuntimeError(f"expected gated open to not call browser again, got {calls['n']}")

            # --force bypasses gating.
            rc = dashboard_open.main(["--project", str(project_root), "--state-file", str(state_file), "--force"])
            if rc != 0:
                raise RuntimeError(f"force open expected rc=0, got {rc}")
            if calls["n"] != 2:
                raise RuntimeError(f"expected force open to call browser again, got {calls['n']}")
        finally:
            webbrowser.open_new = orig_open_new

    print("DASHBOARD OPEN TEST PASSED")


if __name__ == "__main__":
    main()

