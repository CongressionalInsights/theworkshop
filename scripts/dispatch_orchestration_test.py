#!/usr/bin/env python3
from __future__ import annotations

import json
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


def set_frontmatter(path: Path, **updates) -> None:
    doc = split_frontmatter(path.read_text(encoding="utf-8", errors="ignore"))
    for key, value in updates.items():
        doc.frontmatter[key] = value
    path.write_text(join_frontmatter(doc), encoding="utf-8")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="theworkshop-dispatch-") as td:
        base = Path(td).resolve()
        project_root = Path(
            run(py("project_new.py") + ["--name", "Dispatch Test", "--base-dir", str(base)]).stdout.strip()
        ).resolve()
        ws_id = run(py("workstream_add.py") + ["--project", str(project_root), "--title", "Dispatch WS"]).stdout.strip()
        wi_1 = run(py("job_add.py") + ["--project", str(project_root), "--workstream", ws_id, "--title", "A"]).stdout.strip()
        wi_2 = run(py("job_add.py") + ["--project", str(project_root), "--workstream", ws_id, "--title", "B", "--depends-on", wi_1]).stdout.strip()

        set_frontmatter(
            project_root / "plan.md",
            agreement_status="agreed",
            agreed_at=now_iso(),
            agreed_notes="dispatch dry-run test",
            status="in_progress",
        )

        run(py("orchestrate_plan.py") + ["--project", str(project_root)])
        run(py("dispatch_orchestration.py") + ["--project", str(project_root), "--dry-run"])

        execution_path = project_root / "outputs" / "orchestration-execution.json"
        if not execution_path.exists():
            raise RuntimeError(f"Missing dispatch execution artifact: {execution_path}")
        payload = json.loads(execution_path.read_text(encoding="utf-8"))
        if payload.get("schema") != "theworkshop.orchestration-execution.v1":
            raise RuntimeError(f"Unexpected schema payload: {payload.get('schema')}")

        summary = payload.get("summary") or {}
        if int(summary.get("job_count") or 0) <= 0:
            raise RuntimeError(f"Expected job_count > 0, got: {summary}")

        log_path = project_root / "logs" / "subagent-dispatch.jsonl"
        if not log_path.exists():
            raise RuntimeError(f"Missing dispatch log: {log_path}")
        content = log_path.read_text(encoding="utf-8", errors="ignore")
        if "spawned" not in content and "completed" not in content:
            raise RuntimeError("Dispatch log missing expected events")

        agents_log = project_root / "logs" / "agents.jsonl"
        if not agents_log.exists():
            raise RuntimeError(f"Missing canonical agents log: {agents_log}")
        agent_events = [
            json.loads(line)
            for line in agents_log.read_text(encoding="utf-8", errors="ignore").splitlines()
            if line.strip()
        ]
        if not agent_events:
            raise RuntimeError("Expected canonical agent events in agents.jsonl")
        if any(str(evt.get("source") or "") != "dispatch" for evt in agent_events):
            raise RuntimeError(f"Expected dispatch source on all dispatch-run events, got: {agent_events}")
        run_ids = {str(evt.get("dispatch_run_id") or "") for evt in agent_events}
        if len(run_ids) != 1 or "" in run_ids:
            raise RuntimeError(f"Expected one non-empty dispatch_run_id across events, got: {run_ids}")

        run(py("dashboard_build.py") + ["--project", str(project_root)])
        dash = json.loads((project_root / "outputs" / "dashboard.json").read_text(encoding="utf-8"))
        dispatch = dash.get("dispatch") or {}
        if str(dispatch.get("mode") or "") != "active":
            raise RuntimeError(f"Expected dispatch mode active for dispatch-run scenario, got: {dispatch}")
        dispatch_counts = dispatch.get("counts") or {}
        if int(dispatch_counts.get("completed") or 0) <= 0:
            raise RuntimeError(f"Expected at least one completed dispatch agent, got: {dispatch_counts}")
        display_summary = str(dispatch.get("display_summary") or "")
        if "executed" not in display_summary or "jobs" not in display_summary:
            raise RuntimeError(f"Expected humanized dispatch display summary, got: {display_summary!r}")

        print("DISPATCH ORCHESTRATION TEST PASSED")


if __name__ == "__main__":
    main()
