#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from twlib import now_iso  # noqa: E402
from twyaml import join_frontmatter, split_frontmatter  # noqa: E402


def py(script: str) -> list[str]:
    return [sys.executable, str(SCRIPTS_DIR / script)]


def run(cmd: list[str], *, check: bool = True, extra_env: dict | None = None) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["THEWORKSHOP_NO_OPEN"] = "1"
    env["THEWORKSHOP_NO_MONITOR"] = "1"
    env["THEWORKSHOP_NO_KEYCHAIN"] = "1"
    if extra_env:
        env.update(extra_env)
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


def set_frontmatter(path: Path, **updates) -> None:
    doc = split_frontmatter(path.read_text(encoding="utf-8", errors="ignore"))
    for k, v in updates.items():
        doc.frontmatter[k] = v
    path.write_text(join_frontmatter(doc), encoding="utf-8")


def get_status(path: Path) -> str:
    return str(split_frontmatter(path.read_text(encoding="utf-8", errors="ignore")).frontmatter.get("status") or "")


def find_job_plan(project_root: Path, wi: str) -> Path:
    matches = list(project_root.glob(f"workstreams/WS-*/jobs/{wi}-*/plan.md"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one job plan for {wi}, got {len(matches)}")
    return matches[0]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="theworkshop-ui-nonfatal-") as td:
        base = Path(td).resolve()
        project_root = Path(run(py("project_new.py") + ["--name", "UI Nonfatal", "--base-dir", str(base)]).stdout.strip())
        ws_id = run(py("workstream_add.py") + ["--project", str(project_root), "--title", "WS"]).stdout.strip()
        wi = run(py("job_add.py") + ["--project", str(project_root), "--workstream", ws_id, "--title", "Job"]).stdout.strip()

        set_frontmatter(project_root / "plan.md", agreement_status="agreed", agreed_at=now_iso(), agreed_notes="ui nonfatal", status="in_progress")

        run(
            py("job_start.py") + ["--project", str(project_root), "--work-item-id", wi],
            extra_env={"THEWORKSHOP_TEST_FAIL_PROJECTOR": "1"},
        )

        if get_status(find_job_plan(project_root, wi)) != "in_progress":
            raise RuntimeError("Expected job status=in_progress even when projector fails")

        events = (project_root / "logs" / "events.jsonl").read_text(encoding="utf-8", errors="ignore")
        if "projection_warning" not in events:
            raise RuntimeError("Expected projection_warning event when projector failure is forced")

        print("LIFECYCLE NONFATAL UI TEST PASSED")


if __name__ == "__main__":
    main()
