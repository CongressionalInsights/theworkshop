#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent


def py(script: str) -> list[str]:
    return [sys.executable, str(SCRIPTS_DIR / script)]


def run(cmd: list[str], *, env: dict[str, str], check: bool = True) -> subprocess.CompletedProcess[str]:
    merged = dict(os.environ)
    merged["THEWORKSHOP_NO_OPEN"] = "1"
    merged["THEWORKSHOP_NO_MONITOR"] = "1"
    merged["THEWORKSHOP_NO_KEYCHAIN"] = "1"
    merged.update(env)
    proc = subprocess.run(cmd, text=True, capture_output=True, env=merged)
    if check and proc.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            f"  cmd={' '.join(cmd)}\n"
            f"  exit={proc.returncode}\n"
            f"  stdout:\n{proc.stdout}\n"
            f"  stderr:\n{proc.stderr}\n"
        )
    return proc


def _capture_memory(
    project_root: Path,
    *,
    env: dict[str, str],
    wi: str,
    agent_id: str,
    source_agent: str,
    statement: str,
) -> None:
    run(
        py("memory_proposal_capture.py")
        + [
            "--project",
            str(project_root),
            "--work-item-id",
            wi,
            "--agent-id",
            agent_id,
            "--source-agent",
            source_agent,
            "--kind",
            "workflow",
            "--statement",
            statement,
            "--evidence",
            f"Evidence for {agent_id}.",
            "--promote-reason",
            f"Durable rule from {agent_id}.",
        ],
        env=env,
    )


def _capture_lesson(
    project_root: Path,
    *,
    env: dict[str, str],
    wi: str,
    agent_id: str,
    source_agent: str,
    recommendation: str,
) -> None:
    run(
        py("lessons_candidate_capture.py")
        + [
            "--project",
            str(project_root),
            "--work-item-id",
            wi,
            "--agent-id",
            agent_id,
            "--source-agent",
            source_agent,
            "--tags",
            "verification,manual",
            "--context",
            f"Manual agent {agent_id} found a reusable execution tactic.",
            "--worked",
            f"Manual agent {agent_id} preserved verification evidence before closeout.",
            "--recommendation",
            recommendation,
        ],
        env=env,
    )


def _statuses_by_agent(record_dir: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted(record_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        out[str(payload.get("agent_id") or "")] = str(payload.get("status") or "")
    return out


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="theworkshop-agent-closeout-") as td:
        base = Path(td).resolve()
        env = {"CODEX_HOME": str(base / ".codex")}

        project_root = Path(
            run(py("project_new.py") + ["--name", "Agent Closeout Test", "--base-dir", str(base)], env=env).stdout.strip()
        ).resolve()
        ws_id = run(py("workstream_add.py") + ["--project", str(project_root), "--title", "Manual WS"], env=env).stdout.strip()
        wi = run(
            py("job_add.py")
            + ["--project", str(project_root), "--workstream", ws_id, "--title", "Manual Job"],
            env=env,
        ).stdout.strip()

        agent_a = "manual-agent-a"
        agent_b = "manual-agent-b"
        statement_a = "Promote manual-agent-a memory only during explicit closeout."
        statement_b = "Promote manual-agent-b memory only during explicit closeout."
        recommendation_a = "Run manual closeout after staging manual-agent-a findings."
        recommendation_b = "Run manual closeout after staging manual-agent-b findings."

        _capture_memory(project_root, env=env, wi=wi, agent_id=agent_a, source_agent="theworkshop_worker", statement=statement_a)
        _capture_memory(project_root, env=env, wi=wi, agent_id=agent_b, source_agent="theworkshop_reviewer", statement=statement_b)
        _capture_lesson(project_root, env=env, wi=wi, agent_id=agent_a, source_agent="theworkshop_worker", recommendation=recommendation_a)
        _capture_lesson(project_root, env=env, wi=wi, agent_id=agent_b, source_agent="theworkshop_reviewer", recommendation=recommendation_b)

        run(
            py("agent_log.py")
            + [
                "--project",
                str(project_root),
                "--event",
                "completed",
                "--agent-id",
                agent_a,
                "--work-item-id",
                wi,
                "--status",
                "completed",
                "--message",
                "Raw terminal-looking manual event.",
                "--source",
                "manual",
                "--no-dashboard",
            ],
            env=env,
        )

        memory_file = Path(env["CODEX_HOME"]) / "memories" / "projects" / "AgentCloseoutTest.md"
        if memory_file.exists():
            raise RuntimeError("Expected raw agent_log terminal event to avoid memory promotion.")
        if (project_root / "notes" / "lessons-index.json").exists():
            raise RuntimeError("Expected raw agent_log terminal event to avoid lesson promotion.")
        if set(_statuses_by_agent(project_root / ".theworkshop" / "memory-proposals").values()) != {"proposed"}:
            raise RuntimeError("Expected raw agent_log terminal event to leave memory proposals untouched.")
        if set(_statuses_by_agent(project_root / ".theworkshop" / "lessons-candidates").values()) != {"proposed"}:
            raise RuntimeError("Expected raw agent_log terminal event to leave lesson candidates untouched.")

        closeout_a = json.loads(
            run(
                py("agent_closeout.py")
                + [
                    "--project",
                    str(project_root),
                    "--agent-id",
                    agent_a,
                    "--work-item-id",
                    wi,
                    "--status",
                    "completed",
                    "--source",
                    "manual",
                    "--agent-type",
                    "worker",
                    "--runtime-agent-name",
                    "theworkshop_worker",
                    "--agent-profile",
                    "theworkshop_worker",
                    "--message",
                    "Manual worker closeout.",
                ],
                env=env,
            ).stdout
        )
        if int((closeout_a.get("memory") or {}).get("candidate_count") or 0) != 1:
            raise RuntimeError(f"Expected manual closeout to see one memory candidate for agent_a, got: {closeout_a}")
        if int((closeout_a.get("memory") or {}).get("promoted_count") or 0) != 1:
            raise RuntimeError(f"Expected manual closeout to promote one memory record for agent_a, got: {closeout_a}")
        if int((closeout_a.get("lessons") or {}).get("candidate_count") or 0) != 1:
            raise RuntimeError(f"Expected manual closeout to see one lesson candidate for agent_a, got: {closeout_a}")
        if int((closeout_a.get("lessons") or {}).get("promoted_count") or 0) != 1:
            raise RuntimeError(f"Expected manual closeout to promote one lesson record for agent_a, got: {closeout_a}")
        if closeout_a.get("learning_errors"):
            raise RuntimeError(f"Expected no closeout learning errors for agent_a, got: {closeout_a}")

        if not memory_file.exists():
            raise RuntimeError(f"Expected manual closeout to create project memory: {memory_file}")
        memory_text = memory_file.read_text(encoding="utf-8")
        if statement_a not in memory_text or statement_b in memory_text:
            raise RuntimeError(f"Expected only agent_a memory to be promoted after first closeout, got:\n{memory_text}")

        lessons_index = json.loads((project_root / "notes" / "lessons-index.json").read_text(encoding="utf-8"))
        lessons = lessons_index.get("lessons") or []
        if len(lessons) != 1 or recommendation_a not in json.dumps(lessons[0]):
            raise RuntimeError(f"Expected only agent_a lesson after first closeout, got: {lessons}")

        memory_statuses = _statuses_by_agent(project_root / ".theworkshop" / "memory-proposals")
        lesson_statuses = _statuses_by_agent(project_root / ".theworkshop" / "lessons-candidates")
        if memory_statuses.get(agent_a) != "promoted" or memory_statuses.get(agent_b) != "proposed":
            raise RuntimeError(f"Expected only agent_a memory promotion after first closeout, got: {memory_statuses}")
        if lesson_statuses.get(agent_a) != "promoted" or lesson_statuses.get(agent_b) != "proposed":
            raise RuntimeError(f"Expected only agent_a lesson promotion after first closeout, got: {lesson_statuses}")

        events = [
            json.loads(line)
            for line in (project_root / "logs" / "agents.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        terminal_a = events[-1]
        if terminal_a.get("closeout_type") != "manual_subagent":
            raise RuntimeError(f"Expected manual closeout metadata on terminal event, got: {terminal_a}")
        if int(terminal_a.get("memory_promoted_count") or 0) != 1 or int(terminal_a.get("lesson_promoted_count") or 0) != 1:
            raise RuntimeError(f"Expected promoted counts on terminal event, got: {terminal_a}")

        closeout_b = json.loads(
            run(
                py("agent_closeout.py")
                + [
                    "--project",
                    str(project_root),
                    "--agent-id",
                    agent_b,
                    "--work-item-id",
                    wi,
                    "--status",
                    "failed",
                    "--source",
                    "external",
                    "--agent-type",
                    "reviewer",
                    "--runtime-agent-name",
                    "theworkshop_reviewer",
                    "--agent-profile",
                    "theworkshop_reviewer",
                    "--message",
                    "External reviewer closeout.",
                ],
                env=env,
            ).stdout
        )
        if int((closeout_b.get("memory") or {}).get("promoted_count") or 0) != 1:
            raise RuntimeError(f"Expected agent_b memory promotion on second closeout, got: {closeout_b}")
        if int((closeout_b.get("lessons") or {}).get("promoted_count") or 0) != 1:
            raise RuntimeError(f"Expected agent_b lesson promotion on second closeout, got: {closeout_b}")

        memory_text = memory_file.read_text(encoding="utf-8")
        if statement_a not in memory_text or statement_b not in memory_text:
            raise RuntimeError(f"Expected both memory entries after second closeout, got:\n{memory_text}")

        lessons_index = json.loads((project_root / "notes" / "lessons-index.json").read_text(encoding="utf-8"))
        lessons = lessons_index.get("lessons") or []
        if len(lessons) != 2:
            raise RuntimeError(f"Expected two promoted lessons after both closeouts, got: {lessons}")

        run(py("dashboard_build.py") + ["--project", str(project_root)], env=env)
        dashboard = json.loads((project_root / "outputs" / "dashboard.json").read_text(encoding="utf-8"))
        subagents = dashboard.get("subagents") or {}
        recent_events = subagents.get("recent_events") or []
        if not recent_events:
            raise RuntimeError("Expected dashboard subagent events after manual closeout.")
        last_raw = recent_events[-1].get("raw") or {}
        if last_raw.get("closeout_type") != "manual_subagent":
            raise RuntimeError(f"Expected dashboard to surface manual closeout raw event, got: {last_raw}")
        if int(last_raw.get("memory_promoted_count") or 0) != 1 or int(last_raw.get("lesson_promoted_count") or 0) != 1:
            raise RuntimeError(f"Expected dashboard raw event to include promotion counts, got: {last_raw}")

        print("AGENT CLOSEOUT TEST PASSED")


if __name__ == "__main__":
    main()
