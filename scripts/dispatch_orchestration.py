#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from learning_store import build_learning_capture_prompt
from tw_tools import run_script
from twlib import now_iso, normalize_str_list, read_md, resolve_project_root
from workflow_contract import compose_execution_prompt, load_workflow_contract


RUNNABLE_STATUSES = {"planned", "blocked", "in_progress"}
SCRIPTS_DIR = Path(__file__).resolve().parent


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload, separators=(",", ":")) + "\n")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def _job_plan_path(project_root: Path, wi: str) -> Path | None:
    matches = list(project_root.glob(f"workstreams/WS-*/jobs/{wi}-*/plan.md"))
    if len(matches) != 1:
        return None
    return matches[0]


def _job_status(project_root: Path, wi: str) -> str:
    plan_path = _job_plan_path(project_root, wi)
    if not plan_path:
        return "missing"
    doc = read_md(plan_path)
    return str(doc.frontmatter.get("status") or "planned").strip()


def _dependency_errors(project_root: Path, wi: str) -> list[str]:
    plan_path = _job_plan_path(project_root, wi)
    if not plan_path:
        return ["job plan missing"]
    doc = read_md(plan_path)
    deps = normalize_str_list(doc.frontmatter.get("depends_on"))
    errors: list[str] = []
    for dep in deps:
        dep_plan = _job_plan_path(project_root, dep)
        if not dep_plan:
            errors.append(f"{dep}=missing")
            continue
        dep_status = str(read_md(dep_plan).frontmatter.get("status") or "planned").strip()
        if dep_status != "done":
            errors.append(f"{dep}={dep_status}")
    return errors


def _extract_groups(payload: dict[str, Any]) -> list[list[str]]:
    raw_groups: Any = None
    for key in ("parallel_groups", "groups", "execution_groups", "waves"):
        if key in payload:
            raw_groups = payload.get(key)
            break
    if not isinstance(raw_groups, list):
        return []

    groups: list[list[str]] = []
    for group in raw_groups:
        items: list[str] = []
        if isinstance(group, list):
            items = [str(item).strip() for item in group if str(item).strip()]
        elif isinstance(group, dict):
            for key in ("work_items", "jobs", "items", "members", "ids"):
                maybe = group.get(key)
                if isinstance(maybe, list):
                    items = [str(item).strip() for item in maybe if str(item).strip()]
                    if items:
                        break
        elif isinstance(group, str):
            token = group.strip()
            if token:
                items = [token]
        if items:
            groups.append(items)
    return groups


def _resolve_max_parallel(project_root: Path, override: int) -> int:
    if override > 0:
        return override
    project_doc = read_md(project_root / "plan.md")
    fm = project_doc.frontmatter
    env_value = str(__import__("os").environ.get("THEWORKSHOP_MAX_PARALLEL_AGENTS") or "").strip()
    if env_value:
        try:
            n = int(env_value)
            if n > 0:
                return n
        except Exception:
            pass
    try:
        n = int(fm.get("max_parallel_agents") or 3)
    except Exception:
        n = 3
    return max(1, n)


def _agent_event(
    project_root: Path,
    dispatch_log: Path,
    payload: dict[str, Any],
    *,
    dispatch_run_id: str = "",
) -> None:
    stamp = now_iso()
    event = {
        "timestamp": stamp,
        "source": "dispatch",
        **payload,
    }
    if dispatch_run_id and not str(event.get("dispatch_run_id") or "").strip():
        event["dispatch_run_id"] = dispatch_run_id
    _append_jsonl(dispatch_log, event)
    _append_jsonl(project_root / "logs" / "agents.jsonl", event)


def _record_execution(project_root: Path, wi: str, label: str, command: str, start_ts: str, end_ts: str, duration: float, exit_code: int) -> None:
    row = {
        "schema": "theworkshop.execution.v1",
        "timestamp": start_ts,
        "end_timestamp": end_ts,
        "duration_sec": round(duration, 3),
        "work_item_id": wi,
        "label": label,
        "command": command,
        "exit_code": int(exit_code),
    }
    _append_jsonl(project_root / "logs" / "execution.jsonl", row)


def _parse_json_output(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw or "{}")
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _curate_learning(project_root: Path, wi: str) -> dict[str, Any]:
    summary = {"memory": {}, "lessons": {}, "errors": []}
    memory_proc = run_script("memory_curate.py", ["--project", str(project_root), "--work-item-id", wi, "--write"], check=False)
    if memory_proc.returncode == 0:
        summary["memory"] = _parse_json_output(memory_proc.stdout)
    else:
        summary["errors"].append(f"memory_curate failed exit={memory_proc.returncode}")

    lessons_proc = run_script("lessons_curate.py", ["--project", str(project_root), "--work-item-id", wi, "--write"], check=False)
    if lessons_proc.returncode == 0:
        summary["lessons"] = _parse_json_output(lessons_proc.stdout)
    else:
        summary["errors"].append(f"lessons_curate failed exit={lessons_proc.returncode}")
    return summary


def _workflow_policy_prompt(project_root: Path) -> str:
    try:
        contract = load_workflow_contract(project_root, missing_ok=True)
    except SystemExit:
        return ""
    if contract is None:
        return ""
    return str(contract.prompt_template or "").strip()


def _run_job(
    project_root: Path,
    wi: str,
    group_index: int,
    args: argparse.Namespace,
    dispatch_log: Path,
    dispatch_run_id: str,
) -> dict[str, Any]:
    start_wall = time.time()
    start_ts = now_iso()
    agent_id = f"dispatch-{wi}-{int(start_wall)}"
    result: dict[str, Any] = {
        "work_item_id": wi,
        "group_index": group_index,
        "status": "queued",
        "agent_id": agent_id,
        "started_at": start_ts,
        "completed_at": "",
        "duration_sec": 0.0,
        "error": "",
    }

    plan_path = _job_plan_path(project_root, wi)
    if not plan_path:
        result["status"] = "failed"
        result["error"] = "missing job plan"
        result["completed_at"] = now_iso()
        return result

    # Resolve and persist agent profile before dispatch.
    resolved_profile_name = "theworkshop_worker"
    resolved_runtime_agent = "theworkshop_worker"
    fallback_agent_type = "worker"
    try:
        proc = run_script(
            "resolve_agent_profile.py",
            ["--project", str(project_root), "--work-item-id", wi, "--write"],
            check=True,
        )
        try:
            resolved_payload = json.loads(proc.stdout or "{}")
        except Exception:
            resolved_payload = {}
        resolved_profile_name = str(resolved_payload.get("resolved_profile") or resolved_profile_name)
        resolved_runtime_agent = str(resolved_payload.get("resolved_runtime_agent") or resolved_runtime_agent)
        fallback_agent_type = str(resolved_payload.get("fallback_agent_type") or fallback_agent_type)
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = f"resolve_agent_profile failed: {exc}"
        result["completed_at"] = now_iso()
        return result

    # Dependency gate for dispatch itself.
    dep_errors = _dependency_errors(project_root, wi)
    if dep_errors:
        _agent_event(
            project_root,
            dispatch_log,
            {
                "event": "blocked",
                "status": "blocked",
                "agent_id": agent_id,
                "agent_type": "worker",
                "work_item_id": wi,
                "group_index": group_index,
                "message": "dependency gate blocked: " + ", ".join(dep_errors),
            },
            dispatch_run_id=dispatch_run_id,
        )
        result["status"] = "blocked"
        result["error"] = "; ".join(dep_errors)
        result["completed_at"] = now_iso()
        result["duration_sec"] = round(time.time() - start_wall, 3)
        return result

    current_status = _job_status(project_root, wi)
    if current_status not in RUNNABLE_STATUSES:
        result["status"] = "skipped"
        result["error"] = f"status={current_status}"
        result["completed_at"] = now_iso()
        result["duration_sec"] = round(time.time() - start_wall, 3)
        return result

    _agent_event(
        project_root,
        dispatch_log,
        {
            "event": "spawned",
            "status": "active",
            "agent_id": agent_id,
            "agent_type": fallback_agent_type,
            "runtime_agent_name": resolved_runtime_agent,
            "agent_profile": resolved_profile_name,
            "work_item_id": wi,
            "group_index": group_index,
            "message": "subagent scheduled",
        },
        dispatch_run_id=dispatch_run_id,
    )

    # Transition to in-progress using the canonical lifecycle command.
    try:
        run_script(
            "job_start.py",
            [
                "--project",
                str(project_root),
                "--work-item-id",
                wi,
                "--no-dashboard",
                "--no-open",
                "--no-monitor",
            ],
            check=True,
        )
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = f"job_start failed: {exc}"
        result["completed_at"] = now_iso()
        result["duration_sec"] = round(time.time() - start_wall, 3)
        _agent_event(
            project_root,
            dispatch_log,
            {
                "event": "failed",
                "status": "failed",
                "agent_id": agent_id,
                "agent_type": "worker",
                "work_item_id": wi,
                "group_index": group_index,
                "message": result["error"],
            },
            dispatch_run_id=dispatch_run_id,
        )
        return result

    prompt_path = plan_path.parent / "prompt.md"
    if prompt_path.exists():
        prompt_text = prompt_path.read_text(encoding="utf-8", errors="ignore")
    else:
        plan_doc = read_md(plan_path)
        prompt_text = (
            f"Work item: {wi}\n"
            f"Title: {plan_doc.frontmatter.get('title') or ''}\n"
            f"Resolved runtime agent: {resolved_runtime_agent}\n"
            f"Fallback agent type: {fallback_agent_type}\n"
            "Execute this job and produce declared outputs/evidence.\n"
            "Follow the job plan and then stop.\n"
        )
    prompt_text = compose_execution_prompt(_workflow_policy_prompt(project_root), prompt_text)
    prompt_text = prompt_text.rstrip() + "\n\n" + build_learning_capture_prompt(
        project_root,
        work_item_id=wi,
        source_agent=resolved_runtime_agent,
        agent_id=agent_id,
    )

    job_logs = plan_path.parent / "logs"
    job_logs.mkdir(parents=True, exist_ok=True)
    prompt_dump_path = job_logs / "dispatch.prompt.txt"
    stdout_path = job_logs / "dispatch.stdout.txt"
    stderr_path = job_logs / "dispatch.stderr.txt"
    last_msg_path = job_logs / "dispatch.last-message.txt"
    prompt_dump_path.write_text(prompt_text, encoding="utf-8", errors="ignore")

    if args.dry_run or args.runner == "none":
        result["status"] = "simulated"
        result["completed_at"] = now_iso()
        result["duration_sec"] = round(time.time() - start_wall, 3)
        _agent_event(
            project_root,
            dispatch_log,
            {
                "event": "completed",
                "status": "completed",
                "agent_id": agent_id,
                "agent_type": fallback_agent_type,
                "runtime_agent_name": resolved_runtime_agent,
                "agent_profile": resolved_profile_name,
                "work_item_id": wi,
                "group_index": group_index,
                "message": "dry-run dispatch completed",
                "duration_sec": result["duration_sec"],
            },
            dispatch_run_id=dispatch_run_id,
        )
        return result

    cmd = [
        "codex",
        "exec",
        "--color",
        "never",
        "--full-auto",
        "--output-last-message",
        str(last_msg_path),
    ] + list(args.codex_arg or [])

    proc_start_ts = now_iso()
    proc_start = time.time()
    try:
        proc = subprocess.run(
            cmd,
            input=prompt_text,
            text=True,
            capture_output=True,
            cwd=str(project_root),
            timeout=(None if args.timeout_sec <= 0 else int(args.timeout_sec)),
        )
        exit_code = int(proc.returncode)
        stdout_text = proc.stdout or ""
        stderr_text = proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        stdout_text = exc.stdout or ""
        stderr_text = (exc.stderr or "") + "\nTimed out"

    proc_end = time.time()
    duration = proc_end - proc_start
    stdout_path.write_text(stdout_text, encoding="utf-8", errors="ignore")
    stderr_path.write_text(stderr_text, encoding="utf-8", errors="ignore")

    proc_end_ts = now_iso()
    _record_execution(
        project_root,
        wi,
        "dispatch/codex_exec",
        " ".join(cmd),
        proc_start_ts,
        proc_end_ts,
        duration,
        exit_code,
    )

    if exit_code != 0:
        learning_summary = _curate_learning(project_root, wi)
        result["status"] = "failed"
        result["error"] = f"codex exec failed exit={exit_code}"
        result["completed_at"] = now_iso()
        result["duration_sec"] = round(time.time() - start_wall, 3)
        _agent_event(
            project_root,
            dispatch_log,
            {
                "event": "failed",
                "status": "failed",
                "agent_id": agent_id,
                "agent_type": fallback_agent_type,
                "runtime_agent_name": resolved_runtime_agent,
                "agent_profile": resolved_profile_name,
                "work_item_id": wi,
                "group_index": group_index,
                "message": result["error"],
                "duration_sec": result["duration_sec"],
                "memory_candidate_count": int((learning_summary.get("memory") or {}).get("candidate_count") or 0),
                "memory_promoted_count": int((learning_summary.get("memory") or {}).get("promoted_count") or 0),
                "lesson_candidate_count": int((learning_summary.get("lessons") or {}).get("candidate_count") or 0),
                "lesson_promoted_count": int((learning_summary.get("lessons") or {}).get("promoted_count") or 0),
                "learning_errors": list(learning_summary.get("errors") or []),
            },
            dispatch_run_id=dispatch_run_id,
        )
        return result

    # Gate completion through canonical workflow.
    try:
        run_script(
            "reward_eval.py",
            ["--project", str(project_root), "--work-item-id", wi, "--no-dashboard", "--no-sync"],
            check=True,
        )
        run_script(
            "truth_eval.py",
            ["--project", str(project_root), "--work-item-id", wi, "--no-dashboard", "--no-sync"],
            check=True,
        )
        if not args.no_complete:
            run_script(
                "job_complete.py",
                ["--project", str(project_root), "--work-item-id", wi, "--no-open", "--no-dashboard"],
                check=True,
            )
    except Exception as exc:
        learning_summary = _curate_learning(project_root, wi)
        result["status"] = "failed"
        result["error"] = f"completion gates failed: {exc}"
        result["completed_at"] = now_iso()
        result["duration_sec"] = round(time.time() - start_wall, 3)
        _agent_event(
            project_root,
            dispatch_log,
            {
                "event": "failed",
                "status": "failed",
                "agent_id": agent_id,
                "agent_type": fallback_agent_type,
                "runtime_agent_name": resolved_runtime_agent,
                "agent_profile": resolved_profile_name,
                "work_item_id": wi,
                "group_index": group_index,
                "message": result["error"],
                "duration_sec": result["duration_sec"],
                "memory_candidate_count": int((learning_summary.get("memory") or {}).get("candidate_count") or 0),
                "memory_promoted_count": int((learning_summary.get("memory") or {}).get("promoted_count") or 0),
                "lesson_candidate_count": int((learning_summary.get("lessons") or {}).get("candidate_count") or 0),
                "lesson_promoted_count": int((learning_summary.get("lessons") or {}).get("promoted_count") or 0),
                "learning_errors": list(learning_summary.get("errors") or []),
            },
            dispatch_run_id=dispatch_run_id,
        )
        return result

    learning_summary = _curate_learning(project_root, wi)
    result["status"] = "completed"
    result["completed_at"] = now_iso()
    result["duration_sec"] = round(time.time() - start_wall, 3)
    _agent_event(
        project_root,
        dispatch_log,
        {
            "event": "completed",
            "status": "completed",
            "agent_id": agent_id,
            "agent_type": fallback_agent_type,
            "runtime_agent_name": resolved_runtime_agent,
            "agent_profile": resolved_profile_name,
            "work_item_id": wi,
            "group_index": group_index,
            "message": "dispatch execution completed",
            "duration_sec": result["duration_sec"],
            "memory_candidate_count": int((learning_summary.get("memory") or {}).get("candidate_count") or 0),
            "memory_promoted_count": int((learning_summary.get("memory") or {}).get("promoted_count") or 0),
            "lesson_candidate_count": int((learning_summary.get("lessons") or {}).get("candidate_count") or 0),
            "lesson_promoted_count": int((learning_summary.get("lessons") or {}).get("promoted_count") or 0),
            "learning_errors": list(learning_summary.get("errors") or []),
        },
        dispatch_run_id=dispatch_run_id,
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Execute TheWorkshop orchestration groups with delegated subagent runs.")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--orchestration", help="Path to orchestration JSON (default: outputs/orchestration.json)")
    parser.add_argument("--group-index", type=int, action="append", help="Only run selected 1-based group indexes")
    parser.add_argument("--max-parallel", type=int, default=0, help="Override max parallel workers")
    parser.add_argument("--runner", choices=["codex", "none"], default="codex", help="Dispatch execution backend")
    parser.add_argument("--codex-arg", action="append", default=[], help="Extra arg passed to `codex exec` (repeatable)")
    parser.add_argument("--timeout-sec", type=int, default=0, help="Per-job codex exec timeout (0 means no timeout)")
    parser.add_argument("--continue-on-error", action="store_true", help="Continue running later groups after a failure")
    parser.add_argument("--dry-run", action="store_true", help="Simulate dispatch without running codex exec")
    parser.add_argument("--no-complete", action="store_true", help="Do not call job_complete after delegated run")
    parser.add_argument("--no-dashboard", action="store_true", help="Skip dashboard rebuild at the end")
    parser.add_argument(
        "--open-policy",
        choices=["always", "once", "manual"],
        default="once",
        help="Dashboard monitoring policy for this dispatch run.",
    )
    parser.add_argument("--no-monitor", action="store_true", help="Do not start monitor runtime at dispatch start")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    orch_path = Path(args.orchestration).expanduser().resolve() if args.orchestration else (project_root / "outputs" / "orchestration.json")
    if not orch_path.exists():
        raise SystemExit(f"Missing orchestration artifact: {orch_path}. Run `theworkshop orchestrate` first.")

    orchestration = _load_json(orch_path)
    groups = _extract_groups(orchestration)
    if not groups:
        raise SystemExit(f"No runnable groups found in {orch_path}")

    selected = set(args.group_index or [])
    selected_groups: list[tuple[int, list[str]]] = []
    for idx, group in enumerate(groups, start=1):
        if selected and idx not in selected:
            continue
        selected_groups.append((idx, group))

    dispatch_log = project_root / "logs" / "subagent-dispatch.jsonl"
    out_path = project_root / "outputs" / "orchestration-execution.json"
    max_parallel = _resolve_max_parallel(project_root, args.max_parallel)
    dispatch_run_id = f"dispatch-{int(time.time())}"

    if not args.no_monitor:
        try:
            monitor_args = ["start", "--project", str(project_root), "--policy", args.open_policy]
            if args.open_policy == "always":
                monitor_args.append("--force-open")
            if args.open_policy == "manual":
                monitor_args.append("--no-open")
            run_script("monitor_runtime.py", monitor_args, check=True)
        except Exception as exc:
            _agent_event(
                project_root,
                dispatch_log,
                {
                    "event": "warning",
                    "status": "warning",
                    "agent_id": "dispatch-monitor",
                    "agent_type": "orchestrator",
                    "work_item_id": "",
                    "group_index": 0,
                    "message": f"monitor_runtime start failed: {exc}",
                },
                dispatch_run_id=dispatch_run_id,
            )

    execution_groups: list[dict[str, Any]] = []
    total_failures = 0

    for group_index, group in selected_groups:
        runnable = [wi for wi in group if _job_status(project_root, wi) in RUNNABLE_STATUSES]
        if not runnable:
            execution_groups.append(
                {
                    "group_index": group_index,
                    "work_items": group,
                    "results": [],
                    "status": "skipped",
                    "reason": "no runnable jobs in group",
                }
            )
            continue

        group_results: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=max(1, min(max_parallel, len(runnable)))) as pool:
            fut_map = {
                pool.submit(_run_job, project_root, wi, group_index, args, dispatch_log, dispatch_run_id): wi
                for wi in runnable
            }
            for fut in as_completed(fut_map):
                wi = fut_map[fut]
                try:
                    res = fut.result()
                except Exception as exc:
                    res = {
                        "work_item_id": wi,
                        "group_index": group_index,
                        "status": "failed",
                        "error": f"unexpected dispatch exception: {exc}",
                        "started_at": now_iso(),
                        "completed_at": now_iso(),
                        "duration_sec": 0.0,
                    }
                if str(res.get("status") or "") in {"failed", "blocked"}:
                    total_failures += 1
                group_results.append(res)

        group_results = sorted(group_results, key=lambda item: str(item.get("work_item_id") or ""))
        group_status = "completed"
        if any(str(r.get("status") or "") in {"failed", "blocked"} for r in group_results):
            group_status = "failed"

        execution_groups.append(
            {
                "group_index": group_index,
                "work_items": group,
                "results": group_results,
                "status": group_status,
            }
        )

        if group_status == "failed" and not args.continue_on_error:
            break

    payload = {
        "schema": "theworkshop.orchestration-execution.v1",
        "generated_at": now_iso(),
        "project": str(project_root),
        "orchestration_path": str(orch_path),
        "max_parallel_agents": max_parallel,
        "dispatch_run_id": dispatch_run_id,
        "dry_run": bool(args.dry_run),
        "runner": args.runner,
        "groups": execution_groups,
        "summary": {
            "group_count": len(execution_groups),
            "job_count": sum(len(g.get("results") or []) for g in execution_groups),
            "completed": sum(
                1
                for g in execution_groups
                for r in (g.get("results") or [])
                if str(r.get("status") or "") == "completed"
            ),
            "simulated": sum(
                1
                for g in execution_groups
                for r in (g.get("results") or [])
                if str(r.get("status") or "") == "simulated"
            ),
            "failed_or_blocked": total_failures,
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if not args.no_dashboard:
        try:
            run_script("dashboard_projector.py", ["--project", str(project_root)], check=True)
        except Exception:
            pass

    print(str(out_path))
    if total_failures > 0 and not args.continue_on_error and not args.dry_run:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
