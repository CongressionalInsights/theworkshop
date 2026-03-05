#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from twyaml import join_frontmatter, split_frontmatter


SCRIPTS_DIR = Path(__file__).resolve().parent


def run(cmd: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["THEWORKSHOP_NO_OPEN"] = "1"
    env["THEWORKSHOP_NO_MONITOR"] = "1"
    env["THEWORKSHOP_NO_KEYCHAIN"] = "1"
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, capture_output=True, env=env)
    if check and proc.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            f"  cmd={' '.join(cmd)}\n"
            f"  exit={proc.returncode}\n"
            f"  stdout:\n{proc.stdout}\n"
            f"  stderr:\n{proc.stderr}\n"
        )
    return proc


def py(script: str) -> list[str]:
    return [sys.executable, str(SCRIPTS_DIR / script)]


def set_frontmatter(path: Path, **updates) -> None:
    doc = split_frontmatter(path.read_text(encoding="utf-8", errors="ignore"))
    for key, value in updates.items():
        doc.frontmatter[key] = value
    path.write_text(join_frontmatter(doc), encoding="utf-8")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="theworkshop-workflow-runner-") as td:
        base_dir = Path(td).resolve()
        project_root = Path(
            run(py("project_new.py") + ["--name", "Workflow Runner Test", "--base-dir", str(base_dir)]).stdout.strip()
        ).resolve()
        ws_id = run(py("workstream_add.py") + ["--project", str(project_root), "--title", "Main"]).stdout.strip()
        wi = run(py("job_add.py") + ["--project", str(project_root), "--workstream", ws_id, "--title", "Dispatch me"]).stdout.strip()

        set_frontmatter(
            project_root / "plan.md",
            agreement_status="agreed",
            agreed_notes="runner test",
        )

        (project_root / "WORKFLOW.md").write_text(
            """---
work_source:
  kind: local_project
polling:
  interval_sec: 1
orchestration:
  auto_refresh: true
validation:
  require_agreement: true
  run_plan_check: true
dispatch:
  runner: none
  no_monitor: true
  open_policy: manual
hooks:
  timeout_sec: 10
---

Workflow runner marker.
""",
            encoding="utf-8",
        )

        workflow_json = run(py("workflow_check.py") + ["--project", str(project_root), "--json"]).stdout
        payload = json.loads(workflow_json)
        if payload.get("dispatch_runner") != "none":
            raise RuntimeError(f"workflow_check did not expose runner=none: {payload}")

        run(py("workflow_runner.py") + ["--project", str(project_root), "--once", "--no-dashboard"])

        orch_path = project_root / "outputs" / "orchestration.json"
        exec_path = project_root / "outputs" / "orchestration-execution.json"
        runner_log = project_root / "logs" / "workflow-runner.jsonl"
        prompt_path = next(project_root.glob(f"workstreams/WS-*/jobs/{wi}-*/logs/dispatch.prompt.txt"))

        for path in (orch_path, exec_path, runner_log, prompt_path):
            if not path.exists():
                raise RuntimeError(f"Expected file missing after runner cycle: {path}")

        prompt_text = prompt_path.read_text(encoding="utf-8", errors="ignore")
        if "Workflow runner marker." not in prompt_text:
            raise RuntimeError(f"Dispatch prompt missing workflow policy body:\n{prompt_text}")
        if "## Current Work Item" not in prompt_text:
            raise RuntimeError(f"Dispatch prompt missing work item separator:\n{prompt_text}")

        events = [json.loads(line) for line in runner_log.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not any(str(item.get("status") or "") == "dispatched" for item in events):
            raise RuntimeError(f"Expected dispatched event in workflow-runner log, got: {events}")

    print("WORKFLOW RUNNER TEST PASSED")


if __name__ == "__main__":
    main()
