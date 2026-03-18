#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def read_text(root: Path, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8", errors="ignore")


def contains_all(text: str, needles: list[str]) -> bool:
    hay = text.lower()
    return all(needle.lower() in hay for needle in needles)


def contains_any(text: str, needles: list[str]) -> bool:
    hay = text.lower()
    return any(needle.lower() in hay for needle in needles)


def check(score: float, max_score: float, cid: str, message: str) -> dict[str, object]:
    return {
        "id": cid,
        "score": score,
        "max_score": max_score,
        "message": message,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Score TheWorkshop skill-surface contract quality for autoresearch benchmarking.")
    parser.add_argument("--repo", default=str(ROOT), help="Repo root to inspect.")
    args = parser.parse_args()

    root = Path(args.repo).expanduser().resolve()
    skill = read_text(root, "SKILL.md")
    prompting = read_text(root, "references/prompting.md")
    workflow = read_text(root, "references/workflow.md")
    templates = read_text(root, "references/templates.md")
    workflow_contract = read_text(root, "scripts/workflow_contract.py")
    explorer = read_text(root, ".codex/agents/theworkshop_explorer.toml")
    loop_worker = read_text(root, ".codex/agents/theworkshop_loop_worker.toml")
    worker = read_text(root, ".codex/agents/theworkshop_worker.toml")
    reviewer = read_text(root, ".codex/agents/theworkshop_reviewer.toml")

    checks: list[dict[str, object]] = []

    score = 0.0
    max_score = 0.0

    s = 1.0 if contains_all(loop_worker, ["re-read the current job plan", "chat memory", "filesystem progress"]) else 0.0
    checks.append(check(s, 1.0, "loop-worker-loop-safe", "Loop worker should explicitly re-open plan/artifacts and rely on filesystem state."))
    score += s
    max_score += 1.0

    s = 1.0 if contains_all(worker, ["current job plan", "verification steps", "do not imply completion"]) else 0.0
    checks.append(check(s, 1.0, "worker-gated-execution", "Worker should anchor execution to the job plan and completion gates."))
    score += s
    max_score += 1.0

    s = 1.0 if contains_all(reviewer, ["acceptance criteria", "verification evidence", "truth/uat blockers"]) else 0.0
    checks.append(check(s, 1.0, "reviewer-gated-closeout", "Reviewer should anchor findings to acceptance criteria, evidence, and closeout blockers."))
    score += s
    max_score += 1.0

    s = 0.0
    if contains_any(explorer, ["ownership boundaries", "dependencies", "evidence"]):
        s += 1.0
    if contains_any(explorer, ["job plan", "declared outputs", "verification path"]):
        s += 1.0
    checks.append(check(s, 2.0, "explorer-plan-awareness", "Explorer should map ownership/evidence and also read the current job plan or verification path."))
    score += s
    max_score += 2.0

    s = 0.0
    if contains_all(prompting, ["filesystem state persists", "conversational memory does not"]):
        s += 1.0
    if contains_all(prompting, ["re-open the current job plan", "existing outputs/evidence", "completion promise"]):
        s += 1.0
    checks.append(check(s, 2.0, "prompting-loop-safety", "Prompting guide should describe self-sufficient loop prompts and re-open existing artifacts."))
    score += s
    max_score += 2.0

    s = 0.0
    if contains_all(templates, ["re-open the current job plan", "chat memory does not"]):
        s += 1.0
    if contains_all(templates, ["stay inside this work-item scope", "update evidence under `artifacts/`"]):
        s += 1.0
    checks.append(check(s, 2.0, "template-loop-contract", "Ralph-ready template should encode scope boundaries and evidence refresh expectations."))
    score += s
    max_score += 2.0

    s = 0.0
    if contains_all(workflow, ["worker", "current job plan", "verification path"]):
        s += 1.0
    if contains_all(workflow, ["reviewer-style agents", "acceptance criteria", "gate state"]):
        s += 1.0
    checks.append(check(s, 2.0, "workflow-role-mapping", "Workflow doc should map delegated roles to job-plan and gate-aware responsibilities."))
    score += s
    max_score += 2.0

    s = 0.0
    if contains_all(skill, ["clear ownership, inputs, outputs, and acceptance criteria"]):
        s += 1.0
    if contains_any(skill, ["verification path", "verification evidence", "gate state"]):
        s += 1.0
    checks.append(check(s, 2.0, "skill-subagent-rules", "Top-level skill guidance should mention both bounded ownership and verification/gate anchoring for subagents."))
    score += s
    max_score += 2.0

    s = 0.0
    if contains_all(workflow_contract, ["if you are blocked", "durable blocker evidence"]):
        s += 1.0
    if contains_any(skill, ["durable blocker evidence", "blocker evidence"]):
        s += 1.0
    if contains_all(worker, ["if you are blocked", "durable blocker evidence"]):
        s += 1.0
    if contains_all(loop_worker, ["if you are blocked", "durable blocker evidence"]):
        s += 1.0
    checks.append(check(s, 4.0, "blocker-evidence-contract", "Workflow policy, top-level skill rules, and worker/loop-worker agents should leave durable blocker evidence instead of hidden status narration."))
    score += s
    max_score += 4.0

    s = 0.0
    if contains_all(skill, ["agent-log", "agent-closeout", "exactly once"]):
        s += 1.0
    if contains_all(workflow, ["agent-log", "agent-closeout", "exactly once"]):
        s += 1.0
    if contains_all(prompting, ["manual/external delegation", "agent-log", "agent-closeout"]):
        s += 1.0
    if contains_all(templates, ["agent-log", "agent-closeout", "manual/external"]):
        s += 1.0
    checks.append(check(s, 4.0, "delegation-telemetry-contract", "Skill docs, workflow docs, prompting guidance, and templates should preserve truthful manual/external delegation telemetry and exactly-once closeout."))
    score += s
    max_score += 4.0

    s = 0.0
    if contains_all(skill, ["stage durable memory proposals", "lesson candidates", "curator agents"]):
        s += 1.0
    if contains_all(workflow, ["stage new memory/lesson findings", "editing durable memory or canonical lesson files directly"]):
        s += 1.0
    if contains_all(prompting, ["stage", "durable memory", "lesson", "instead of editing"]) or contains_all(prompting, ["memory proposals", "lesson candidates"]):
        s += 1.0
    if contains_all(templates, ["memory proposals", "lesson candidates"]) or contains_all(templates, ["stage", "durable memory", "canonical lesson"]):
        s += 1.0
    checks.append(check(s, 4.0, "staged-learning-contract", "Skill docs, workflow docs, prompting guidance, and templates should reinforce staged learning and curator-only durable writes."))
    score += s
    max_score += 4.0

    summary = f"{score:.1f}/{max_score:.1f} contract points"
    sys_payload = {
        "score": score,
        "max_score": max_score,
        "summary": summary,
        "checks": checks,
    }
    print(json.dumps(sys_payload, indent=2))


if __name__ == "__main__":
    main()
