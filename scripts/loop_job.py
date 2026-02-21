#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from plan_sync import sync_project_plans
from twlib import now_iso, normalize_str_list, read_md, resolve_project_root, write_md


LOOP_MODE_ALLOWED = {"until_complete", "max_iterations", "promise_or_max"}
LOOP_STATUS_VALUES = {"active", "stopped", "completed", "blocked", "error"}


@dataclass
class IterationResult:
    attempt: int
    exit_code: int
    started_at: str
    stopped_at: str
    duration_sec: float
    prompt: str
    last_promise: str
    last_message_path: Path
    stdout_path: Path
    stderr_path: Path


def append_progress_log(body: str, line: str) -> str:
    heading = "# Progress Log"
    if heading not in body:
        return body.rstrip() + "\n\n" + heading + "\n\n" + f"- {line}\n"

    pre, rest = body.split(heading, 1)
    rest_lines = rest.splitlines()
    insert_at = len(rest_lines)
    for i, ln in enumerate(rest_lines[1:], start=1):
        if ln.startswith("# "):
            insert_at = i
            break
    new_rest = rest_lines[:insert_at] + [f"- {line}"] + rest_lines[insert_at:]
    return (pre + heading + "\n" + "\n".join(new_rest)).rstrip() + "\n"


def append_decision_log(body: str, line: str) -> str:
    heading = "# Decisions"
    if heading not in body:
        return body.rstrip() + "\n\n" + heading + "\n\n" + f"- {line}\n"

    pre, rest = body.split(heading, 1)
    rest_lines = rest.splitlines()
    insert_at = len(rest_lines)
    for i, ln in enumerate(rest_lines[1:], start=1):
        if ln.startswith("# "):
            insert_at = i
            break
    new_rest = rest_lines[:insert_at] + [f"- {line}"] + rest_lines[insert_at:]
    return (pre + heading + "\n" + "\n".join(new_rest)).rstrip() + "\n"


def parse_jsonish(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None

    fenced = re.search(r"```json\s*(.*?)\s*```", text, flags=re.I | re.S)
    if fenced:
        text = fenced.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        text = text[start : end + 1]

    try:
        payload = json.loads(text)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def normalize_promise(raw: str) -> str:
    return " ".join((raw or "").strip().split())


def parse_promise(raw: str) -> str:
    match = re.search(r"<promise>(.*?)</promise>", raw or "", flags=re.I | re.S)
    if not match:
        return ""
    return normalize_promise(match.group(1) or "")


def parse_env_bool(name: str) -> bool:
    return os.environ.get(name, "").strip() == "1"


def env_no_open() -> bool:
    return parse_env_bool("THEWORKSHOP_NO_OPEN")


def env_no_monitor() -> bool:
    return parse_env_bool("THEWORKSHOP_NO_MONITOR")


def run_py(script: str, argv: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    scripts_dir = Path(__file__).resolve().parent
    proc = subprocess.run([sys.executable, str(scripts_dir / script)] + argv, text=True, capture_output=True)
    if check and proc.returncode != 0:
        raise SystemExit(
            "command failed:\n"
            f"  cmd={' '.join(shlex.quote(part) for part in proc.args)}\n"
            f"  exit={proc.returncode}\n"
            f"  stdout:\n{proc.stdout}\n"
            f"  stderr:\n{proc.stderr}"
        )
    return proc


def run_py_best_effort(script: str, argv: list[str]) -> None:
    try:
        run_py(script, argv)
    except Exception as exc:
        print(f"warning: {script} failed (best-effort): {exc}", file=sys.stderr)


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def append_execution_row(project_root: Path, row: dict[str, Any]) -> None:
    row.setdefault("schema", "theworkshop.execution.v1")
    log_path = project_root / "logs" / "execution.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(row) + "\n")


def file_nonempty(path: Path) -> bool:
    try:
        return path.exists() and path.is_file() and path.stat().st_size > 0
    except Exception:
        return False


def find_job_dir(project_root: Path, wi: str) -> Path:
    matches = list(project_root.glob(f"workstreams/WS-*/jobs/{wi}-*"))
    if len(matches) != 1:
        raise SystemExit(f"Expected exactly 1 job dir for {wi}, got {len(matches)}: {matches}")
    return matches[0]


def parent_workstream_dir(project_root: Path, job_dir: Path) -> Path:
    rel = job_dir.relative_to(project_root)
    parts = rel.parts
    if len(parts) < 4 or parts[0] != "workstreams" or parts[2] != "jobs":
        raise SystemExit(f"Unexpected job path layout: {job_dir}")
    return project_root / parts[0] / parts[1]


def resolve_dependency_errors(project_root: Path, fm: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for dep in normalize_str_list(fm.get("depends_on")):
        matches = list(project_root.glob(f"workstreams/WS-*/jobs/{dep}-*/plan.md"))
        if len(matches) != 1:
            errors.append(f"{dep}=missing")
            continue
        dep_doc = read_md(matches[0])
        dep_status = str(dep_doc.frontmatter.get("status") or "planned").strip()
        if dep_status != "done":
            errors.append(f"{dep}={dep_status}")
    return errors


def validate_completion_promise(value: str) -> None:
    if not value:
        raise SystemExit("completion promise is required for promise-based loop modes.")
    if "\n" in value or "\r" in value:
        raise SystemExit("completion promise must be a single line.")
    if "<" in value or ">" in value:
        raise SystemExit("completion promise must not contain angle brackets.")


def stakes_default_iterations(stakes: str) -> int:
    return {"low": 2, "normal": 3, "high": 5, "critical": 7}.get((stakes or "").strip().lower(), 3)


def resolve_loop_config(fm: dict[str, Any], args: argparse.Namespace) -> tuple[str, int, str]:
    configured_mode = str(fm.get("loop_mode") or "").strip().lower()
    if configured_mode not in LOOP_MODE_ALLOWED:
        configured_mode = ""
    mode = str(args.mode or configured_mode or "").strip().lower()
    if not mode:
        mode = "max_iterations"

    max_loops = int(args.max_loops or 0)
    if not max_loops:
        max_loops = int(fm.get("loop_max_iterations") or 0)
    if not max_loops:
        max_loops = int(fm.get("max_iterations") or 0)
    if not max_loops:
        max_loops = stakes_default_iterations(str(fm.get("stakes") or "normal"))

    completion_promise = (
        args.completion_promise.strip()
        or str(fm.get("loop_target_promise") or "").strip()
        or str(fm.get("completion_promise") or "").strip()
    )

    require_promise = mode in {"until_complete", "promise_or_max"}
    if require_promise and not completion_promise and max_loops <= 0:
        raise SystemExit("completion promise is required when no finite loop cap is configured.")

    if require_promise and completion_promise:
        validate_completion_promise(completion_promise)

    return mode, int(max_loops), completion_promise


def run_preflight(prompt: str, completion_promise: str, project_root: Path, codex_args: list[str], threshold: int) -> None:
    if threshold <= 0:
        return

    pre_prompt = (
        "You are evaluating a task prompt for a Ralph-style loop that repeatedly runs \"codex exec\" with the SAME prompt each iteration.\n"
        "The agent does not retain chat memory between iterations, but it does retain filesystem state.\n\n"
        "Goal: determine how likely this prompt is to complete in repeated loop execution.\n\n"
        "Return STRICT JSON only (no code fences, no extra text) with keys:\n"
        '"score": integer 0-100\\n'
        '"issues": array of short strings (empty if none)\\n'
        '"improved_prompt": a revised prompt that is ready to use\\n\n'
        "Requirements for improved_prompt:\n"
        "- Must be self-contained and specific.\\n"
        "- Must include explicit acceptance criteria.\\n"
        "- Must include test/command steps."
    )
    if completion_promise:
        pre_prompt += f"- MUST include the completion promise exactly as: <promise>{completion_promise}</promise>\\n"
    pre_prompt += f"\nPROMPT TO EVALUATE:\n<<<\n{prompt}\n>>>"

    cmd = [
        "codex",
        "exec",
        "--output-last-message",
        "/dev/null",
        "--color",
        "never",
        "--full-auto",
    ] + codex_args
    proc = subprocess.run(cmd, text=True, input=pre_prompt, capture_output=True, cwd=str(project_root))
    if proc.returncode != 0:
        raise SystemExit(
            "preflight failed: codex exec returned non-zero.\n"
            f"exit={proc.returncode}\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}"
        )

    payload = parse_jsonish(proc.stdout)
    if not payload:
        raise SystemExit("preflight failed: could not parse JSON from codex output.")

    score = int(payload.get("score", 0) or 0)
    if score < threshold:
        issues = payload.get("issues") or []
        if not isinstance(issues, list):
            issues = [issues]
        issue_text = "; ".join(str(item).strip() for item in issues if str(item).strip())
        if not issue_text:
            issue_text = "no structured issue detail available"
        raise SystemExit(f"preflight failed: score={score} below threshold={threshold}. {issue_text}")


def run_one_execution(
    project_root: Path,
    wi: str,
    attempt: int,
    prompt: str,
    codex_args: list[str],
) -> IterationResult:
    loops_dir = project_root / "logs" / "loops" / wi
    loops_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = loops_dir / f"attempt-{attempt}.stdout.txt"
    stderr_path = loops_dir / f"attempt-{attempt}.stderr.txt"
    last_message_path = loops_dir / f"attempt-{attempt}.last-message.txt"

    start_ts = now_iso()
    start_epoch = time.time()

    cmd = [
        "codex",
        "exec",
        "--output-last-message",
        str(last_message_path),
        "--color",
        "never",
    ] + codex_args

    proc = subprocess.run(cmd, text=True, input=prompt, capture_output=True, cwd=str(project_root))
    stopped = now_iso()
    duration = time.time() - start_epoch

    stdout_path.write_text(proc.stdout or "", encoding="utf-8", errors="ignore")
    stderr_path.write_text(proc.stderr or "", encoding="utf-8", errors="ignore")

    try:
        last_message = last_message_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        last_message = ""
    promise_text = parse_promise(last_message)

    append_execution_row(
        project_root,
        {
            "timestamp": start_ts,
            "end_timestamp": stopped,
            "duration_sec": int(round(duration)),
            "label": "loop_job",
            "level": "INFO" if proc.returncode == 0 else "ERROR",
            "tags": ["loop", f"attempt:{attempt}", f"wi:{wi}"],
            "work_item_id": wi,
            "phase": "loop",
            "command": " ".join(shlex.quote(part) for part in cmd),
            "cwd": str(project_root),
            "exit_code": int(proc.returncode),
            "stdout": str(stdout_path),
            "stderr": str(stderr_path),
            "last_message": str(last_message_path),
        },
    )

    return IterationResult(
        attempt=attempt,
        exit_code=int(proc.returncode),
        started_at=start_ts,
        stopped_at=stopped,
        duration_sec=duration,
        prompt=prompt,
        last_promise=promise_text,
        last_message_path=last_message_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
    )


def write_attempt_state(
    project_root: Path,
    wi: str,
    *,
    loop_mode: str,
    loop_max_iterations: int,
    loop_target_promise: str,
    max_walltime_sec: int,
    loop_status: str,
    loop_last_attempt: int,
    loop_last_started_at: str,
    loop_last_stopped_at: str,
    loop_stop_reason: str,
    result: IterationResult,
) -> None:
    payload = {
        "schema": "theworkshop.loop-state.v1",
        "project": str(project_root),
        "work_item_id": wi,
        "loop_mode": loop_mode,
        "loop_max_iterations": int(loop_max_iterations),
        "loop_target_promise": loop_target_promise,
        "loop_status": loop_status,
        "loop_last_attempt": int(loop_last_attempt),
        "loop_last_started_at": loop_last_started_at,
        "loop_last_stopped_at": loop_last_stopped_at,
        "loop_stop_reason": loop_stop_reason,
        "max_walltime_sec": int(max_walltime_sec),
        "last_attempt": {
            "attempt": int(loop_last_attempt),
            "started_at": result.started_at,
            "stopped_at": result.stopped_at,
            "duration_sec": float(result.duration_sec),
            "exit_code": int(result.exit_code),
            "last_promise": result.last_promise,
            "last_message_path": str(result.last_message_path),
            "stdout_path": str(result.stdout_path),
            "stderr_path": str(result.stderr_path),
        },
    }
    write_json(project_root / ".theworkshop" / "loops" / wi / "state.json", payload)


def write_summary(
    project_root: Path,
    wi: str,
    *,
    loop_mode: str,
    loop_max_iterations: int,
    completion_promise: str,
    loop_status: str,
    loop_last_attempt: int,
    loop_last_started_at: str,
    loop_last_stopped_at: str,
    loop_stop_reason: str,
    max_walltime_sec: int,
    start_type: str,
    elapsed_sec: int,
) -> None:
    write_json(
        project_root / ".theworkshop" / "loops" / wi / "summary.json",
        {
            "schema": "theworkshop.loop-state.v1",
            "project": str(project_root),
            "work_item_id": wi,
            "loop_mode": loop_mode,
            "loop_max_iterations": int(loop_max_iterations),
            "max_walltime_sec": int(max_walltime_sec),
            "loop_target_promise": completion_promise,
            "loop_status": loop_status,
            "loop_last_attempt": int(loop_last_attempt),
            "loop_last_started_at": loop_last_started_at,
            "loop_last_stopped_at": loop_last_stopped_at,
            "loop_stop_reason": loop_stop_reason,
            "duration_sec": int(elapsed_sec),
            "start_type": start_type,
        },
    )


def update_job_loop_fields(
    job_plan: Path,
    *,
    progress: str | None = None,
    status: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    doc = read_md(job_plan)
    fm = doc.frontmatter
    for key, value in kwargs.items():
        if value is not None:
            fm[key] = value
    if status is not None:
        fm["status"] = status
    fm["updated_at"] = now_iso()
    if progress:
        doc.body = append_progress_log(doc.body, progress)
    write_md(job_plan, doc)
    return read_md(job_plan).frontmatter


def project_decision(project_root: Path, line: str) -> None:
    doc = read_md(project_root / "plan.md")
    doc.body = append_decision_log(doc.body, line)
    doc.frontmatter["updated_at"] = now_iso()
    write_md(project_root / "plan.md", doc)


def run_gates(project_root: Path) -> tuple[bool, str]:
    reward = run_py("reward_eval.py", ["--project", str(project_root), "--no-sync", "--no-dashboard"], check=False)
    if reward.returncode != 0:
        return False, "reward_eval"

    truth = run_py("truth_eval.py", ["--project", str(project_root), "--no-sync", "--no-dashboard"], check=False)
    if truth.returncode != 0:
        return False, "truth_eval"

    plan = run_py("plan_check.py", ["--project", str(project_root), "--strict"], check=False)
    if plan.returncode != 0:
        return False, "plan_check"

    return True, ""


def completion_ready(job_plan: Path, *, require_promise: bool, target_promise: str, last_promise: str) -> bool:
    doc = read_md(job_plan)
    fm = doc.frontmatter

    target = int(fm.get("reward_target") or 0)
    score = int(fm.get("reward_last_score") or 0)
    if score < target:
        return False

    if str(fm.get("truth_last_status") or "").strip().lower() != "pass":
        return False

    outputs = normalize_str_list(fm.get("outputs"))
    evidence = normalize_str_list(fm.get("verification_evidence"))
    if not outputs or not evidence:
        return False
    if any(not file_nonempty(doc_dir := Path(job_plan).parent / rel) for rel in outputs):
        return False
    if any(not file_nonempty(doc_dir := Path(job_plan).parent / rel) for rel in evidence):
        return False

    if require_promise and target_promise:
        return normalize_promise(last_promise) == normalize_promise(target_promise)
    return True


def run_job_completion(project_root: Path, wi: str, *, no_open: bool, no_dashboard: bool) -> int:
    args = ["--project", str(project_root), "--work-item-id", wi, "--cascade"]
    if no_open:
        args.append("--no-open")
    if no_dashboard:
        args.append("--no-dashboard")
    proc = run_py("job_complete.py", args, check=False)
    return proc.returncode


def start_dashboard(project_root: Path, *, no_dashboard: bool, no_open: bool) -> None:
    if no_dashboard:
        return
    run_py("dashboard_build.py", ["--project", str(project_root)])
    if not no_open:
        run_py_best_effort("dashboard_open.py", ["--project", str(project_root), "--once"])
    if not env_no_monitor():
        run_py_best_effort("dashboard_watch.py", ["--project", str(project_root)])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a TheWorkshop job with Ralph-style repeated Codex execution.")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--work-item-id", required=True, help="WI-... to execute")
    parser.add_argument(
        "--mode",
        choices=sorted(LOOP_MODE_ALLOWED),
        help="Loop mode: until_complete, max_iterations, or promise_or_max.",
    )
    parser.add_argument("--max-loops", type=int, default=0, help="Max attempts (0=derive from plan/defaults)")
    parser.add_argument(
        "--max-walltime-sec",
        type=int,
        default=0,
        help="Optional hard stop walltime cap in seconds (0=unlimited).",
    )
    parser.add_argument("--completion-promise", default="", help="Exact completion promise to stop on in promise modes.")
    parser.add_argument(
        "--codex-arg",
        action="append",
        default=[],
        help="Additional argument for each codex exec call (repeatable).",
    )
    parser.add_argument("--no-preflight", action="store_true", help="Skip codex preflight check.")
    parser.add_argument("--preflight-threshold", type=int, default=75, help="Minimum preflight score (0-100).")
    parser.add_argument("--resume", action="store_true", help="Resume from persisted loop state.")
    parser.add_argument(
        "--allow-unmet-deps",
        action="store_true",
        help="Allow start/loop despite unfinished dependencies (requires --decision-note).",
    )
    parser.add_argument(
        "--no-override",
        action="store_true",
        help="Compatibility alias for --allow-unmet-deps.",
    )
    parser.add_argument("--decision-note", default="", help="Required when overriding dependency gates.")
    parser.add_argument("--no-open", action="store_true", help="Skip dashboard auto-open.")
    parser.add_argument("--no-dashboard", action="store_true", help="Skip dashboard rebuild/monitor.")
    return parser.parse_args()


def _walltime_exceeded(start_ts: float, limit: int) -> bool:
    return bool(limit and (time.time() - start_ts) >= limit)


def _start_attempt(base: int, fm: dict[str, Any], *, resume: bool, state: dict[str, Any]) -> int:
    if not resume:
        return max(1, int(base))
    return max(
        int(state.get("loop_last_attempt") or 0),
        int(fm.get("loop_last_attempt") or 0),
        base,
    ) + 1


def main() -> None:
    args = parse_args()
    project_root = resolve_project_root(args.project)
    wi = args.work_item_id.strip()

    if args.max_walltime_sec < 0:
        raise SystemExit("--max-walltime-sec must be >= 0")
    if not (0 <= args.preflight_threshold <= 100):
        raise SystemExit("--preflight-threshold must be 0..100")

    no_open = args.no_open or env_no_open()
    no_dashboard = args.no_dashboard or parse_env_bool("THEWORKSHOP_NO_DASHBOARD")

    job_dir = find_job_dir(project_root, wi)
    job_plan = job_dir / "plan.md"
    prompt_path = job_dir / "prompt.md"
    prompt = prompt_path.read_text(encoding="utf-8", errors="ignore") if prompt_path.exists() else ""
    if not prompt.strip():
        raise SystemExit("Missing or empty prompt file.")

    project_plan = read_md(project_root / "plan.md")
    job_plan_doc = read_md(job_plan)
    project_fm = project_plan.frontmatter
    job_fm = job_plan_doc.frontmatter

    if str(project_fm.get("agreement_status") or "").strip() != "agreed":
        raise SystemExit("agreement_status must be 'agreed' before loop execution.")
    project_status = str(project_fm.get("status") or "").strip()
    if project_status in {"done", "cancelled"}:
        raise SystemExit(f"Cannot execute loop while project status={project_status!r}")

    job_status = str(job_fm.get("status") or "planned").strip()
    if job_status in {"done", "cancelled"}:
        raise SystemExit(f"Cannot execute loop while job status={job_status!r}")

    ws_dir = parent_workstream_dir(project_root, job_dir)
    ws_status = str(read_md(ws_dir / "plan.md").frontmatter.get("status") or "").strip()
    if ws_status in {"done", "cancelled"}:
        raise SystemExit(f"Cannot execute loop while workstream status={ws_status!r}")

    allow_override = bool(args.allow_unmet_deps or args.no_override)
    unmet = resolve_dependency_errors(project_root, job_fm)
    if unmet and not allow_override:
        raise SystemExit("Cannot run loop with unmet dependencies: " + ", ".join(unmet))
    if unmet:
        if not args.decision_note.strip():
            raise SystemExit("--allow-unmet-deps/--no-override requires --decision-note")
        project_decision(
            project_root,
            f"{now_iso()} dependency override for {wi}: {', '.join(unmet)}; note: {args.decision_note.strip()}",
        )
        job_plan_doc.body = append_progress_log(
            job_plan_doc.body,
            f"{now_iso()} dependency override: {', '.join(unmet)}; note: {args.decision_note.strip()}",
        )
        write_md(job_plan, job_plan_doc)

    loop_mode, max_loops, completion_promise = resolve_loop_config(job_fm, args)

    require_promise = loop_mode in {"until_complete", "promise_or_max"}
    if require_promise and max_loops <= 0 and not completion_promise:
        raise SystemExit("completion promise required for promise modes when max iterations is unlimited.")
    if not require_promise and max_loops <= 0:
        max_loops = stakes_default_iterations(str(job_fm.get("stakes") or "normal"))

    loop_state_path = project_root / ".theworkshop" / "loops" / wi / "state.json"
    loop_state = read_json(loop_state_path)
    loop_start_ts = now_iso()

    ts = now_iso()
    update_job_loop_fields(
        job_plan,
        progress=(
            f"{ts} loop start: mode={loop_mode}; max_loops={int(max_loops)}; max_walltime_sec={int(args.max_walltime_sec or 0)}; "
            f"completion_promise={completion_promise or '<none>'}"
        ),
        loop_enabled=True,
        loop_mode=loop_mode,
        loop_max_iterations=int(max_loops),
        loop_target_promise=completion_promise,
        loop_status="active",
        loop_last_started_at=loop_start_ts,
        loop_last_stopped_at="",
        loop_stop_reason="",
    )
    project_decision(
        project_root,
        (
            f"{ts} loop decision: WI={wi} mode={loop_mode}; max_loops={int(max_loops)}; "
            f"max_walltime_sec={int(args.max_walltime_sec or 0)}; completion_promise={completion_promise or '<none>'}; "
            f"preflight={'on' if not args.no_preflight else 'off'}; resume={args.resume}"
        ),
    )

    if not args.no_preflight:
        run_preflight(
            prompt=prompt,
            completion_promise=completion_promise,
            project_root=project_root,
            codex_args=args.codex_arg,
            threshold=int(args.preflight_threshold),
        )

    if str(job_plan_doc.frontmatter.get("status") or "") != "in_progress":
        start_args = ["--project", str(project_root), "--work-item-id", wi]
        if no_open:
            start_args.append("--no-open")
        if no_dashboard:
            start_args.append("--no-dashboard")
        if allow_override:
            start_args.extend(["--allow-unmet-deps", "--decision-note", args.decision_note])
        run_py("job_start.py", start_args)
        job_plan_doc = read_md(job_plan)

    start_dashboard(project_root, no_dashboard=no_dashboard, no_open=no_open)

    attempt = _start_attempt(
        int(job_plan_doc.frontmatter.get("iteration") or 0),
        job_plan_doc.frontmatter,
        resume=args.resume,
        state=loop_state,
    )

    loop_dir = project_root / ".theworkshop" / "loops" / wi
    loop_dir.mkdir(parents=True, exist_ok=True)
    cancel_marker = loop_dir / "cancel"

    start_wall = time.time()
    loop_status = "active"
    stop_reason = ""
    final_code = 0
    loop_done = False
    last_attempt = attempt
    last_started_at = ""
    last_stopped_at = ""

    while True:
        now = now_iso()

        if _walltime_exceeded(start_wall, int(args.max_walltime_sec or 0)):
            loop_status = "blocked"
            stop_reason = "timeout"
            break

        if max_loops > 0 and attempt > max_loops:
            loop_status = "blocked"
            stop_reason = "max_iterations"
            break

        if cancel_marker.exists():
            loop_status = "stopped"
            stop_reason = "cancel"
            break

        last_started_at = now
        update_job_loop_fields(
            job_plan,
            status="in_progress",
            progress=f"{now} loop attempt {attempt} begin",
            loop_status="active",
            loop_last_attempt=attempt,
            loop_last_started_at=now,
            loop_last_stopped_at="",
            loop_stop_reason="",
            loop_max_iterations=int(max_loops),
            loop_mode=loop_mode,
            loop_target_promise=completion_promise,
        )

        result = run_one_execution(
            project_root=project_root,
            wi=wi,
            attempt=attempt,
            prompt=prompt,
            codex_args=args.codex_arg,
        )

        update_job_loop_fields(
            job_plan,
            progress=f"{result.stopped_at} loop attempt {attempt} codex exit={result.exit_code}; output={result.stdout_path}; errors={result.stderr_path}",
            loop_status="active",
            loop_last_attempt=attempt,
            loop_last_started_at=result.started_at,
            loop_last_stopped_at=result.stopped_at,
            loop_stop_reason="",
            iteration=attempt,
            loop_mode=loop_mode,
            loop_max_iterations=int(max_loops),
            loop_target_promise=completion_promise,
        )
        write_attempt_state(
            project_root=project_root,
            wi=wi,
            loop_mode=loop_mode,
            loop_max_iterations=int(max_loops),
            loop_target_promise=completion_promise,
            max_walltime_sec=int(args.max_walltime_sec or 0),
            loop_status="active",
            loop_last_attempt=attempt,
            loop_last_started_at=result.started_at,
            loop_last_stopped_at=result.stopped_at,
            loop_stop_reason="",
            result=result,
        )

        last_attempt = attempt
        last_stopped_at = result.stopped_at

        if result.exit_code != 0:
            final_code = result.exit_code
            loop_status = "error"
            stop_reason = f"exit_code_{result.exit_code}"
            break

        gates_ok, gate_stage = run_gates(project_root)
        if not gates_ok:
            update_job_loop_fields(
                job_plan,
                loop_status="active",
                loop_last_stopped_at=result.stopped_at,
                loop_stop_reason=f"gates_{gate_stage}_failed",
                progress=(
                    f"{result.stopped_at} loop attempt {attempt}: gates not passed ({gate_stage}); continuing"
                ),
                iteration=attempt,
            )
            attempt += 1
            sync_project_plans(project_root, ts=now_iso())
            if not no_dashboard:
                run_py("dashboard_build.py", ["--project", str(project_root)], check=False)
            continue

        if completion_ready(
            job_plan,
            require_promise=require_promise,
            target_promise=completion_promise,
            last_promise=result.last_promise,
        ):
            complete_code = run_job_completion(project_root, wi, no_open=no_open, no_dashboard=no_dashboard)
            if complete_code == 0:
                loop_status = "completed"
                stop_reason = "promise_detected" if require_promise and result.last_promise else "completed"
                loop_done = True
                final_code = 0
                update_job_loop_fields(
                    job_plan,
                    status="done",
                    loop_status="completed",
                    loop_last_stopped_at=result.stopped_at,
                    loop_stop_reason=stop_reason,
                    progress=(
                        f"{result.stopped_at} loop attempt {attempt}: completion checks passed; job_complete succeeded."
                    ),
                )
                break

            final_code = complete_code
            loop_status = "error"
            stop_reason = "job_complete_failed"
            update_job_loop_fields(
                job_plan,
                loop_status="error",
                loop_last_stopped_at=result.stopped_at,
                loop_stop_reason=stop_reason,
                progress=f"{result.stopped_at} loop attempt {attempt}: job_complete failed (exit={complete_code}).",
            )
            break

        update_job_loop_fields(
            job_plan,
            loop_status="active",
            loop_last_stopped_at=result.stopped_at,
            loop_stop_reason="gates_passed_not_complete",
            progress=(
                f"{result.stopped_at} loop attempt {attempt}: gates passed but completion criteria not met "
                f"(promise_match={bool(normalize_promise(result.last_promise) == normalize_promise(completion_promise)) if require_promise else 'n/a'})."
            ),
            iteration=attempt,
        )

        attempt += 1
        sync_project_plans(project_root, ts=now_iso())
        if not no_dashboard:
            run_py("dashboard_build.py", ["--project", str(project_root)], check=False)

    elapsed = int(round(time.time() - start_wall))
    final_stopped = last_stopped_at or now_iso()
    final_reason = stop_reason or ("completed" if loop_done else "error")

    write_attempt_state(
        project_root=project_root,
        wi=wi,
        loop_mode=loop_mode,
        loop_max_iterations=int(max_loops),
        loop_target_promise=completion_promise,
        max_walltime_sec=int(args.max_walltime_sec or 0),
        loop_status=loop_status,
        loop_last_attempt=last_attempt,
        loop_last_started_at=last_started_at or loop_start_ts,
        loop_last_stopped_at=final_stopped,
        loop_stop_reason=final_reason,
        result=IterationResult(
            attempt=last_attempt,
            exit_code=final_code,
            started_at=last_started_at or loop_start_ts,
            stopped_at=final_stopped,
            duration_sec=max(0.0, elapsed),
            prompt=prompt,
            last_promise="",
            last_message_path=project_root / "logs" / "loops" / wi / f"attempt-{last_attempt}.last-message.txt",
            stdout_path=project_root / "logs" / "loops" / wi / f"attempt-{last_attempt}.stdout.txt",
            stderr_path=project_root / "logs" / "loops" / wi / f"attempt-{last_attempt}.stderr.txt",
        ),
    )
    write_summary(
        project_root=project_root,
        wi=wi,
        loop_mode=loop_mode,
        loop_max_iterations=int(max_loops),
        completion_promise=completion_promise,
        loop_status=loop_status,
        loop_last_attempt=last_attempt,
        loop_last_started_at=last_started_at or loop_start_ts,
        loop_last_stopped_at=final_stopped,
        loop_stop_reason=final_reason,
        max_walltime_sec=int(args.max_walltime_sec or 0),
        start_type="resume" if args.resume else "fresh",
        elapsed_sec=elapsed,
    )

    update_job_loop_fields(
        job_plan,
        loop_status=loop_status,
        loop_last_attempt=last_attempt,
        loop_last_stopped_at=final_stopped,
        loop_stop_reason=final_reason,
        progress=(
            f"{final_stopped} loop finished: wi={wi}; mode={loop_mode}; attempts={last_attempt}; "
            f"status={loop_status}; reason={final_reason}"
        ),
        loop_mode=loop_mode,
        loop_max_iterations=int(max_loops),
        loop_target_promise=completion_promise,
    )
    project_decision(
        project_root,
        (
            f"{final_stopped} loop decision: WI={wi} status={loop_status}; reason={final_reason}; "
            f"attempts={last_attempt}; mode={loop_mode}; max_loops={int(max_loops)}"
        ),
    )

    sync_project_plans(project_root, ts=final_stopped)
    if not no_dashboard:
        run_py("dashboard_build.py", ["--project", str(project_root)], check=False)
        if not no_open:
            run_py_best_effort("dashboard_open.py", ["--project", str(project_root), "--once"])

    if loop_done:
        print(
            f"loop finished: {wi} status=completed attempts={last_attempt} reason={final_reason}"
        )
        return

    if loop_status == "blocked":
        print(
            f"loop finished: {wi} status=blocked reason={final_reason} attempts={last_attempt}"
        )
        raise SystemExit(1)

    if loop_status == "error":
        print(f"loop finished: {wi} status=error reason={final_reason} attempts={last_attempt}")
        raise SystemExit(final_code or 1)

    print(f"loop finished: {wi} status={loop_status} reason={final_reason} attempts={last_attempt}")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
