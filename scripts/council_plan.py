#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from twlib import now_iso, read_md, resolve_project_root


SCRIPT_DIR = Path(__file__).resolve().parent


@dataclass
class PlannerSpec:
    name: str
    provider: str
    model: str


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload, separators=(",", ":")) + "\n")


def _event(project_root: Path, event: str, status: str, message: str, planner: str = "") -> None:
    payload = {
        "timestamp": now_iso(),
        "event": event,
        "status": status,
        "agent_id": planner or f"council-{event}",
        "agent_type": "planner",
        "work_item_id": "",
        "message": message,
    }
    _append_jsonl(project_root / "logs" / "agents.jsonl", payload)


def _parse_jsonish(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None
    # Direct JSON first.
    try:
        payload = json.loads(raw)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    # Fenced JSON.
    marker_start = raw.find("```json")
    if marker_start >= 0:
        marker_end = raw.find("```", marker_start + 7)
        if marker_end > marker_start:
            block = raw[marker_start + 7 : marker_end].strip()
            try:
                payload = json.loads(block)
                if isinstance(payload, dict):
                    return payload
            except Exception:
                pass
    # Best-effort brace extraction.
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        chunk = raw[start : end + 1]
        try:
            payload = json.loads(chunk)
            if isinstance(payload, dict):
                return payload
        except Exception:
            return None
    return None


def _planner_specs(project_doc: dict[str, Any]) -> tuple[list[PlannerSpec], PlannerSpec]:
    fm = project_doc
    raw_planners = fm.get("council_planners")
    planners: list[PlannerSpec] = []

    if isinstance(raw_planners, list):
        for idx, item in enumerate(raw_planners, start=1):
            token = str(item or "").strip()
            if not token:
                continue
            if ":" in token:
                provider, model = token.split(":", 1)
            else:
                provider, model = "gemini", token
            provider = provider.strip().lower() or "gemini"
            model = model.strip() or "gemini-2.5-pro"
            planners.append(PlannerSpec(name=f"planner-{idx}", provider=provider, model=model))

    if not planners:
        planners = [
            PlannerSpec(name="planner-1", provider="gemini", model="gemini-2.5-pro"),
            PlannerSpec(name="planner-2", provider="gemini", model="gemini-2.5-flash"),
            PlannerSpec(name="planner-3", provider="gemini", model="gemini-2.5-flash-lite"),
        ]

    judge_raw = str(fm.get("council_judge") or "").strip()
    if judge_raw:
        if ":" in judge_raw:
            p, m = judge_raw.split(":", 1)
            judge = PlannerSpec(name="judge", provider=p.strip().lower() or "gemini", model=m.strip())
        else:
            judge = PlannerSpec(name="judge", provider="gemini", model=judge_raw)
    else:
        first = planners[0]
        judge = PlannerSpec(name="judge", provider=first.provider, model=first.model)

    return planners, judge


def _build_task_brief(project_root: Path) -> dict[str, Any]:
    project = read_md(project_root / "plan.md")
    body = project.body

    def section_text(heading: str) -> str:
        if heading not in body:
            return ""
        pre, rest = body.split(heading, 1)
        _ = pre
        lines = rest.splitlines()
        out: list[str] = []
        for line in lines[1:]:
            if line.startswith("# "):
                break
            out.append(line)
        return "\n".join(out).strip()

    return {
        "project_id": str(project.frontmatter.get("id") or ""),
        "project_title": str(project.frontmatter.get("title") or ""),
        "goal": section_text("# Goal"),
        "acceptance": section_text("# Acceptance Criteria"),
        "workstreams": section_text("# Workstreams"),
        "constraints": {
            "subagent_policy": str(project.frontmatter.get("subagent_policy") or "auto"),
            "max_parallel_agents": int(project.frontmatter.get("max_parallel_agents") or 3),
            "agreement_status": str(project.frontmatter.get("agreement_status") or "proposed"),
        },
    }


def _planner_prompt(brief: dict[str, Any], planner_name: str, focus: str) -> str:
    return (
        "You are one planner in TheWorkshop council. Produce an independent plan.\n"
        "Do not ask questions. Use assumptions explicitly.\n"
        "Return STRICT JSON only with keys:"
        " planner, assumptions, risks, decomposition, dependencies, waves, success_hooks, agreement_questions, final_notes.\n"
        "Where decomposition is an array of workstream objects:"
        " {id,title,purpose,jobs:[{id,title,depends_on,outputs,verification,success_hook}]}.\n"
        "Focus style: "
        + focus
        + "\n\n"
        + "PROJECT BRIEF JSON:\n"
        + json.dumps(brief, indent=2)
        + "\n"
        + f"\nPlanner name: {planner_name}\n"
    )


def _judge_prompt(brief: dict[str, Any], anonymized_plans: list[dict[str, Any]]) -> str:
    return (
        "You are council judge for TheWorkshop.\n"
        "Choose and merge best elements across anonymous plans.\n"
        "Return STRICT JSON only with keys: selected_plan_id, rationale, merged_plan_markdown, decision_log.\n"
        "merged_plan_markdown must be actionable and include Project->Workstreams->Jobs plus explicit success hooks.\n"
        "Do not mention vendor/model names.\n\n"
        "PROJECT BRIEF JSON:\n"
        + json.dumps(brief, indent=2)
        + "\n\n"
        + "ANONYMIZED CANDIDATE PLANS JSON:\n"
        + json.dumps(anonymized_plans, indent=2)
    )


def _run_gemini(model: str, prompt: str) -> tuple[int, str, str]:
    cmd = ["gemini", "--output-format", "json", "--model", model, prompt]
    proc = subprocess.run(cmd, text=True, capture_output=True)
    return int(proc.returncode), proc.stdout or "", proc.stderr or ""


def _run_openai_with_keychain(model: str, prompt: str, approve: str) -> tuple[int, str, str]:
    codex_home = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex"))
    keychain = codex_home / "skills" / "apple-keychain" / "scripts" / "keychain_run.sh"
    if not keychain.exists():
        return 2, "", f"apple-keychain script missing: {keychain}"

    with tempfile.TemporaryDirectory(prefix="theworkshop-council-openai-") as td:
        tmp = Path(td)
        prompt_path = tmp / "prompt.txt"
        out_path = tmp / "out.txt"
        runner = tmp / "runner.py"
        prompt_path.write_text(prompt, encoding="utf-8")
        runner.write_text(
            "import json\n"
            "import os\n"
            "from openai import OpenAI\n"
            "prompt = open(os.environ['TW_PROMPT_PATH'], 'r', encoding='utf-8').read()\n"
            "client = OpenAI(api_key=os.environ.get('OPENAI_API_KEY', ''))\n"
            "resp = client.responses.create(model=os.environ['TW_OPENAI_MODEL'], input=prompt)\n"
            "text = getattr(resp, 'output_text', '') or ''\n"
            "print(text)\n",
            encoding="utf-8",
        )

        base_cmd: list[str]
        if shutil.which("uv"):
            base_cmd = ["uv", "run", "--with", "openai", "python", str(runner)]
        else:
            base_cmd = [sys.executable, str(runner)]

        env_prefix = [
            "env",
            f"TW_PROMPT_PATH={prompt_path}",
            f"TW_OPENAI_MODEL={model}",
        ]
        full = [
            str(keychain),
            "run",
            "--type",
            "generic",
            "--service",
            "OPENAI_KEY",
            "--match",
            "--env",
            "OPENAI_API_KEY",
            "--approve",
            approve,
            "--",
        ] + env_prefix + base_cmd

        proc = subprocess.run(full, text=True, capture_output=True)
        out_path.write_text(proc.stdout or "", encoding="utf-8", errors="ignore")
        return int(proc.returncode), proc.stdout or "", proc.stderr or ""


def _run_planner(spec: PlannerSpec, prompt: str, retries: int, approve: str) -> dict[str, Any]:
    last_stdout = ""
    last_stderr = ""
    for attempt in range(1, retries + 2):
        if spec.provider == "gemini":
            rc, out, err = _run_gemini(spec.model, prompt)
        elif spec.provider == "openai":
            rc, out, err = _run_openai_with_keychain(spec.model, prompt, approve)
        else:
            return {
                "ok": False,
                "attempts": attempt,
                "error": f"unsupported provider: {spec.provider}",
                "stdout": "",
                "stderr": "",
                "payload": {},
            }

        last_stdout, last_stderr = out, err
        if rc != 0:
            continue

        payload = _parse_jsonish(out)
        if payload is None:
            continue
        return {
            "ok": True,
            "attempts": attempt,
            "error": "",
            "stdout": out,
            "stderr": err,
            "payload": payload,
        }

    return {
        "ok": False,
        "attempts": retries + 1,
        "error": "planner output invalid or command failed",
        "stdout": last_stdout,
        "stderr": last_stderr,
        "payload": {},
    }


def _mock_plan(spec: PlannerSpec, brief: dict[str, Any], focus: str) -> dict[str, Any]:
    project_id = brief.get("project_id") or "PJ-UNKNOWN"
    return {
        "planner": spec.name,
        "assumptions": ["Dry-run mode: generated deterministic placeholder plan."],
        "risks": ["Dry-run output should not be treated as final planning guidance."],
        "decomposition": [
            {
                "id": f"WS-{project_id}-001",
                "title": f"{focus} workstream",
                "purpose": "Council draft placeholder",
                "jobs": [
                    {
                        "id": f"WI-{project_id}-001",
                        "title": "Draft scoped plan",
                        "depends_on": [],
                        "outputs": ["outputs/primary.md"],
                        "verification": ["artifacts/verification.md"],
                        "success_hook": "outputs produced and verified",
                    }
                ],
            }
        ],
        "dependencies": [],
        "waves": ["Wave 1"],
        "success_hooks": ["All jobs include acceptance criteria + verification + completion promise."],
        "agreement_questions": ["Confirm decomposition and priority order before execution."],
        "final_notes": "Dry-run council plan.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run optional multi-planner council synthesis before agreement gate.")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--out-dir", help="Output directory (default: outputs/council)")
    parser.add_argument("--retries", type=int, default=1, help="Retries per planner/judge parse failure")
    parser.add_argument("--seed", type=int, default=42, help="Randomization seed for anonymized ordering")
    parser.add_argument("--approve", default="ttl:1h", help="apple-keychain approval mode for OpenAI provider")
    parser.add_argument("--dry-run", action="store_true", help="Do not call providers; generate deterministic mock outputs")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    project_doc = read_md(project_root / "plan.md")
    brief = _build_task_brief(project_root)
    planners, judge = _planner_specs(project_doc.frontmatter)

    out_dir = Path(args.out_dir).expanduser().resolve() if args.out_dir else (project_root / "outputs" / "council")
    out_dir.mkdir(parents=True, exist_ok=True)

    _event(project_root, "council_started", "active", f"planners={len(planners)} judge={judge.provider}:{judge.model}")

    planner_results: list[dict[str, Any]] = []
    focus_modes = ["decomposition-first", "risk-first", "timeline-first", "verification-first"]

    for idx, spec in enumerate(planners, start=1):
        focus = focus_modes[(idx - 1) % len(focus_modes)]
        prompt = _planner_prompt(brief, spec.name, focus)
        if args.dry_run:
            payload = _mock_plan(spec, brief, focus)
            result = {"ok": True, "attempts": 0, "error": "", "stdout": "", "stderr": "", "payload": payload}
        else:
            result = _run_planner(spec, prompt, max(0, args.retries), args.approve)

        entry = {
            "planner": spec.__dict__,
            "focus": focus,
            "ok": bool(result.get("ok")),
            "attempts": int(result.get("attempts") or 0),
            "error": str(result.get("error") or ""),
            "payload": result.get("payload") if isinstance(result.get("payload"), dict) else {},
        }
        planner_results.append(entry)

        (out_dir / f"planner-{idx:02d}.json").write_text(json.dumps(entry, indent=2) + "\n", encoding="utf-8")
        md_lines = [
            f"# Planner {idx}: {spec.name}",
            "",
            f"- Provider: {spec.provider}",
            f"- Model: {spec.model}",
            f"- Focus: {focus}",
            f"- OK: {entry['ok']}",
            f"- Attempts: {entry['attempts']}",
        ]
        if entry["error"]:
            md_lines.append(f"- Error: {entry['error']}")
        md_lines.append("")
        md_lines.append("```json")
        md_lines.append(json.dumps(entry.get("payload") or {}, indent=2))
        md_lines.append("```")
        (out_dir / f"planner-{idx:02d}.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")

        _event(project_root, "planner_completed", "completed" if entry["ok"] else "failed", f"{spec.name} ok={entry['ok']}", spec.name)

    ok_plans = [item for item in planner_results if item.get("ok") and isinstance(item.get("payload"), dict)]
    if not ok_plans:
        _event(project_root, "council_failed", "failed", "all planners failed")
        raise SystemExit("No valid planner outputs produced.")

    anonymized: list[dict[str, Any]] = []
    for idx, item in enumerate(ok_plans, start=1):
        anonymized.append(
            {
                "anonymous_id": f"candidate-{idx}",
                "focus": item.get("focus"),
                "payload": item.get("payload"),
            }
        )
    rng = random.Random(int(args.seed))
    rng.shuffle(anonymized)

    judge_prompt = _judge_prompt(brief, anonymized)
    if args.dry_run:
        judge_payload = {
            "selected_plan_id": anonymized[0]["anonymous_id"],
            "rationale": "dry-run selected first randomized candidate",
            "merged_plan_markdown": "# Council Draft\n\nDry-run council output.",
            "decision_log": ["Dry-run only."],
        }
        judge_result = {"ok": True, "attempts": 0, "error": "", "payload": judge_payload, "stdout": "", "stderr": ""}
    else:
        judge_result = _run_planner(judge, judge_prompt, max(0, args.retries), args.approve)

    if not judge_result.get("ok"):
        _event(project_root, "judge_failed", "failed", str(judge_result.get("error") or "judge failed"), "judge")
        raise SystemExit(f"Judge failed: {judge_result.get('error')}")

    judge_payload = judge_result.get("payload") if isinstance(judge_result.get("payload"), dict) else {}
    merged_md = str(judge_payload.get("merged_plan_markdown") or "").strip() or "# Council Draft\n\nNo merged markdown was returned."

    final_payload = {
        "schema": "theworkshop.council.v1",
        "generated_at": now_iso(),
        "project": str(project_root),
        "brief": brief,
        "planners": planner_results,
        "anonymized_order": [item.get("anonymous_id") for item in anonymized],
        "judge": {
            "provider": judge.provider,
            "model": judge.model,
            "attempts": int(judge_result.get("attempts") or 0),
            "payload": judge_payload,
        },
        "final": {
            "selected_plan_id": str(judge_payload.get("selected_plan_id") or ""),
            "rationale": str(judge_payload.get("rationale") or ""),
            "decision_log": judge_payload.get("decision_log") if isinstance(judge_payload.get("decision_log"), list) else [],
        },
    }

    (out_dir / "council-plan.json").write_text(json.dumps(final_payload, indent=2) + "\n", encoding="utf-8")
    (out_dir / "final-plan.md").write_text(merged_md.rstrip() + "\n", encoding="utf-8")

    _event(project_root, "council_completed", "completed", f"selected={final_payload['final']['selected_plan_id']}")

    print(str(out_dir / "council-plan.json"))


if __name__ == "__main__":
    main()
