#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from workflow_contract import compose_execution_prompt, load_workflow_contract


SCRIPTS_DIR = Path(__file__).resolve().parent


def run(cmd: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["THEWORKSHOP_NO_OPEN"] = "1"
    env["THEWORKSHOP_NO_MONITOR"] = "1"
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


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="theworkshop-workflow-contract-") as td:
        base_dir = Path(td).resolve()
        project_root = Path(
            run(py("project_new.py") + ["--name", "Workflow Contract Test", "--base-dir", str(base_dir)]).stdout.strip()
        ).resolve()

        contract = load_workflow_contract(project_root)
        if contract is None:
            raise RuntimeError("Expected default WORKFLOW.md to load")
        if contract.work_source_kind != "local_project":
            raise RuntimeError(f"Unexpected work_source_kind: {contract.work_source_kind}")
        if contract.dispatch_runner != "codex":
            raise RuntimeError(f"Unexpected dispatch runner: {contract.dispatch_runner}")

        os.environ["THEWORKSHOP_TEST_CODEX_ARGS"] = "--model gpt-5.4 --config shell_environment_policy.inherit=all"
        (project_root / "WORKFLOW.md").write_text(
            """---
work_source:
  kind: local_project
polling:
  interval_sec: 5
dispatch:
  runner: none
  max_parallel: 2
  timeout_sec: 90
  continue_on_error: true
  no_monitor: true
  open_policy: manual
  codex_args: $THEWORKSHOP_TEST_CODEX_ARGS
hooks:
  timeout_sec: 15
---

Runner policy marker.
""",
            encoding="utf-8",
        )

        contract = load_workflow_contract(project_root)
        assert contract is not None
        if contract.dispatch_runner != "none":
            raise RuntimeError(f"Expected runner none, got {contract.dispatch_runner}")
        if contract.dispatch_max_parallel != 2:
            raise RuntimeError(f"Expected max_parallel=2, got {contract.dispatch_max_parallel}")
        if contract.dispatch_timeout_sec != 90:
            raise RuntimeError(f"Expected timeout_sec=90, got {contract.dispatch_timeout_sec}")
        if contract.dispatch_open_policy != "manual":
            raise RuntimeError(f"Expected open_policy=manual, got {contract.dispatch_open_policy}")
        if contract.dispatch_codex_args[:2] != ["--model", "gpt-5.4"]:
            raise RuntimeError(f"Unexpected codex args: {contract.dispatch_codex_args}")

        prompt = compose_execution_prompt(contract.prompt_template, "job-specific prompt")
        if "Runner policy marker." not in prompt or "## Current Work Item" not in prompt:
            raise RuntimeError(f"Composed prompt missing workflow body separator:\n{prompt}")

    print("WORKFLOW CONTRACT TEST PASSED")


if __name__ == "__main__":
    main()
