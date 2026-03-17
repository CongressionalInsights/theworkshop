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


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="theworkshop-learning-curate-") as td:
        base = Path(td).resolve()
        env = {"CODEX_HOME": str(base / ".codex")}

        project_root = Path(
            run(py("project_new.py") + ["--name", "Learning Curate Test", "--base-dir", str(base)], env=env).stdout.strip()
        ).resolve()
        ws_id = run(py("workstream_add.py") + ["--project", str(project_root), "--title", "Curate WS"], env=env).stdout.strip()
        wi = run(
            py("job_add.py")
            + ["--project", str(project_root), "--workstream", ws_id, "--title", "Curate Job"],
            env=env,
        ).stdout.strip()

        run(
            py("memory_proposal_capture.py")
            + [
                "--project",
                str(project_root),
                "--work-item-id",
                wi,
                "--source-agent",
                "theworkshop_worker",
                "--kind",
                "workflow",
                "--statement",
                "Stage durable memory through proposal files before promoting it.",
                "--evidence",
                "Observed during delegated execution.",
                "--promote-reason",
                "This is a stable workshop operating rule.",
            ],
            env=env,
        )
        run(
            py("memory_proposal_capture.py")
            + [
                "--project",
                str(project_root),
                "--work-item-id",
                wi,
                "--source-agent",
                "theworkshop_reviewer",
                "--kind",
                "workflow",
                "--statement",
                "Stage durable memory through proposal files before promoting it.",
                "--evidence",
                "Repeated by reviewer pass.",
                "--promote-reason",
                "Duplicate signal should merge cleanly.",
            ],
            env=env,
        )

        run(
            py("lessons_candidate_capture.py")
            + [
                "--project",
                str(project_root),
                "--work-item-id",
                wi,
                "--source-agent",
                "theworkshop_worker",
                "--tags",
                "verification,delegation",
                "--context",
                "Delegated work produced a reusable verification tactic.",
                "--worked",
                "Capturing the verification artifact before closing the job prevented a false complete.",
                "--recommendation",
                "Record verification evidence before attempting job completion.",
            ],
            env=env,
        )
        run(
            py("lessons_candidate_capture.py")
            + [
                "--project",
                str(project_root),
                "--work-item-id",
                wi,
                "--source-agent",
                "theworkshop_reviewer",
                "--tags",
                "verification",
                "--context",
                "Closeout review found the same reusable tactic.",
                "--worked",
                "Capturing the verification artifact before closing the job prevented a false complete.",
                "--recommendation",
                "Record verification evidence before attempting job completion.",
            ],
            env=env,
        )

        memory_dry = json.loads(run(py("memory_curate.py") + ["--project", str(project_root), "--work-item-id", wi], env=env).stdout)
        lessons_dry = json.loads(run(py("lessons_curate.py") + ["--project", str(project_root), "--work-item-id", wi], env=env).stdout)
        if int(memory_dry.get("promotable_count") or 0) != 1:
            raise RuntimeError(f"Expected one promotable memory group, got: {memory_dry}")
        if int(lessons_dry.get("promotable_count") or 0) != 1:
            raise RuntimeError(f"Expected one promotable lesson group, got: {lessons_dry}")

        memory_write = json.loads(
            run(py("memory_curate.py") + ["--project", str(project_root), "--work-item-id", wi, "--write"], env=env).stdout
        )
        lessons_write = json.loads(
            run(py("lessons_curate.py") + ["--project", str(project_root), "--work-item-id", wi, "--write"], env=env).stdout
        )
        if int(memory_write.get("promoted_count") or 0) != 1:
            raise RuntimeError(f"Expected one promoted memory item, got: {memory_write}")
        if int(lessons_write.get("promoted_count") or 0) != 1:
            raise RuntimeError(f"Expected one promoted lesson item, got: {lessons_write}")

        memory_file = Path(env["CODEX_HOME"]) / "memories" / "projects" / "LearningCurateTest.md"
        if not memory_file.exists():
            raise RuntimeError(f"Expected curated memory file: {memory_file}")
        memory_text = memory_file.read_text(encoding="utf-8")
        if memory_text.count("Stage durable memory through proposal files before promoting it.") != 1:
            raise RuntimeError(f"Expected deduped memory entry, got:\n{memory_text}")

        lessons_md = project_root / "notes" / "lessons-learned.md"
        lessons_index = project_root / "notes" / "lessons-index.json"
        if not lessons_md.exists() or not lessons_index.exists():
            raise RuntimeError("Expected lessons artifacts to exist after curation.")
        index_payload = json.loads(lessons_index.read_text(encoding="utf-8"))
        lessons = index_payload.get("lessons") or []
        if len(lessons) != 1:
            raise RuntimeError(f"Expected one promoted lesson, got: {lessons}")

        proposal_dir = project_root / ".theworkshop" / "memory-proposals"
        proposal_statuses = [json.loads(path.read_text(encoding="utf-8")).get("status") for path in sorted(proposal_dir.glob("*.json"))]
        if proposal_statuses != ["promoted", "promoted"]:
            raise RuntimeError(f"Expected promoted memory proposal statuses, got: {proposal_statuses}")

        candidate_dir = project_root / ".theworkshop" / "lessons-candidates"
        candidate_statuses = [json.loads(path.read_text(encoding="utf-8")).get("status") for path in sorted(candidate_dir.glob("*.json"))]
        if candidate_statuses != ["promoted", "promoted"]:
            raise RuntimeError(f"Expected promoted lesson candidate statuses, got: {candidate_statuses}")

        print("LEARNING CURATE TEST PASSED")


if __name__ == "__main__":
    main()
