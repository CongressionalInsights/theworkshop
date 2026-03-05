#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from tw_tools import run_script
from twlib import now_iso, read_md, resolve_project_root
from workflow_contract import WorkflowContract, load_workflow_contract


RUNNABLE_STATUSES = {"planned", "blocked", "in_progress"}


def _state_path(project_root: Path) -> Path:
    return project_root / "tmp" / "workflow-runner.json"


def _event_log_path(project_root: Path) -> Path:
    return project_root / "logs" / "workflow-runner.jsonl"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload, separators=(",", ":")) + "\n")


def _pid_alive(pid: int) -> bool:
    if pid <= 1:
        return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _project_status(project_root: Path) -> tuple[str, str]:
    doc = read_md(project_root / "plan.md")
    status = str(doc.frontmatter.get("status") or "planned").strip()
    agreement = str(doc.frontmatter.get("agreement_status") or "proposed").strip()
    return status, agreement


def _job_plan_path(project_root: Path, wi: str) -> Path | None:
    matches = list(project_root.glob(f"workstreams/WS-*/jobs/{wi}-*/plan.md"))
    if len(matches) != 1:
        return None
    return matches[0]


def _job_status(project_root: Path, wi: str) -> str:
    plan_path = _job_plan_path(project_root, wi)
    if not plan_path:
        return "missing"
    return str(read_md(plan_path).frontmatter.get("status") or "planned").strip()


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


def _orchestration_groups(project_root: Path) -> list[list[str]]:
    orch_path = project_root / "outputs" / "orchestration.json"
    payload = _load_json(orch_path)
    return _extract_groups(payload)


def _runnable_groups(project_root: Path) -> list[list[str]]:
    groups = _orchestration_groups(project_root)
    out: list[list[str]] = []
    for group in groups:
        runnable = [wi for wi in group if _job_status(project_root, wi) in RUNNABLE_STATUSES]
        if runnable:
            out.append(runnable)
    return out


def _truncate(text: str, limit: int = 1200) -> str:
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[:limit] + "... (truncated)"


def _runner_event(project_root: Path, event: str, status: str, message: str, **extra: Any) -> None:
    payload = {
        "timestamp": now_iso(),
        "event": event,
        "status": status,
        "message": message,
        **extra,
    }
    _append_jsonl(_event_log_path(project_root), payload)


def _run_hook(project_root: Path, label: str, command: str, timeout_sec: int) -> tuple[bool, str]:
    hook = str(command or "").strip()
    if not hook:
        return True, ""
    try:
        proc = subprocess.run(
            ["sh", "-lc", hook],
            cwd=str(project_root),
            text=True,
            capture_output=True,
            timeout=max(1, timeout_sec),
        )
    except subprocess.TimeoutExpired:
        return False, f"{label} hook timed out after {timeout_sec}s"
    except Exception as exc:
        return False, f"{label} hook failed to start: {exc}"

    output = _truncate((proc.stdout or "") + "\n" + (proc.stderr or ""))
    if proc.returncode != 0:
        return False, f"{label} hook exited {proc.returncode}: {output}"
    return True, output


def _refresh_orchestration(project_root: Path) -> tuple[bool, str]:
    result = run_script("orchestrate_plan.py", ["--project", str(project_root)], check=False)
    if result.returncode != 0:
        return False, _truncate((result.stdout or "") + "\n" + (result.stderr or ""))
    return True, _truncate(result.stdout or result.stderr or "")


def _run_dispatch(project_root: Path, contract: WorkflowContract, *, no_dashboard: bool) -> tuple[int, str]:
    argv = ["--project", str(project_root)]
    if contract.dispatch_runner != "codex":
        argv += ["--runner", contract.dispatch_runner]
    if contract.dispatch_max_parallel > 0:
        argv += ["--max-parallel", str(contract.dispatch_max_parallel)]
    if contract.dispatch_timeout_sec > 0:
        argv += ["--timeout-sec", str(contract.dispatch_timeout_sec)]
    if contract.dispatch_continue_on_error:
        argv.append("--continue-on-error")
    if contract.dispatch_no_complete:
        argv.append("--no-complete")
    if contract.dispatch_no_monitor:
        argv.append("--no-monitor")
    if contract.dispatch_open_policy:
        argv += ["--open-policy", contract.dispatch_open_policy]
    if no_dashboard:
        argv.append("--no-dashboard")
    for arg in contract.dispatch_codex_args:
        argv += ["--codex-arg", arg]

    result = run_script("dispatch_orchestration.py", argv, check=False)
    message = _truncate((result.stdout or "") + "\n" + (result.stderr or ""))
    return result.returncode, message


def _refresh_dashboard(project_root: Path, *, warning: str, no_dashboard: bool) -> None:
    if no_dashboard:
        return
    argv = ["--project", str(project_root)]
    if warning.strip():
        argv += ["--warning", warning.strip()]
    run_script("dashboard_projector.py", argv, check=False)


def _detach_self(project_root: Path, args: argparse.Namespace, *, pid_file: Path, log_file: Path) -> int:
    state = _load_json(pid_file)
    pid = int(state.get("pid") or 0)
    if _pid_alive(pid):
        return 0

    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--project",
        str(project_root),
        "--workflow",
        str(args.workflow or ""),
        "--interval-sec",
        str(float(args.interval_sec or 0)),
        "--max-cycles",
        str(int(args.max_cycles or 0)),
        "--max-seconds",
        str(int(args.max_seconds or 0)),
        "--pid-file",
        str(pid_file),
        "--log-file",
        str(log_file),
    ]
    if args.no_dashboard:
        cmd.append("--no-dashboard")

    log_file.parent.mkdir(parents=True, exist_ok=True)
    with log_file.open("a", encoding="utf-8") as fh:
        fh.write(f"{now_iso()} workflow_runner: detaching: {' '.join(cmd)}\n")

    out = log_file.open("a", encoding="utf-8")
    try:
        subprocess.Popen(
            cmd,
            stdout=out,
            stderr=out,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
    except Exception as exc:
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(f"{now_iso()} workflow_runner: detach failed: {exc}\n")
        return 2
    return 0


def _cycle(project_root: Path, workflow_path: str | None, *, no_dashboard: bool) -> tuple[dict[str, Any], bool]:
    status, agreement = _project_status(project_root)
    if status in {"done", "cancelled"}:
        result = {
            "cycle_at": now_iso(),
            "status": "terminal",
            "message": f"project status is {status}",
            "exit_code": 0,
            "workflow_path": str(workflow_path or project_root / "WORKFLOW.md"),
        }
        _runner_event(project_root, "cycle_skipped", "terminal", result["message"])
        _refresh_dashboard(project_root, warning="", no_dashboard=no_dashboard)
        return result, False

    try:
        contract = load_workflow_contract(project_root, workflow_path=workflow_path)
        assert contract is not None
    except SystemExit as exc:
        message = str(exc)
        result = {
            "cycle_at": now_iso(),
            "status": "workflow_error",
            "message": message,
            "exit_code": 1,
            "workflow_path": str(workflow_path or project_root / "WORKFLOW.md"),
        }
        _runner_event(project_root, "cycle_failed", "workflow_error", message)
        _refresh_dashboard(project_root, warning=message, no_dashboard=no_dashboard)
        return result, True

    if contract.validation_require_agreement and agreement != "agreed":
        message = f"agreement_status={agreement}; waiting for agreement"
        result = {
            "cycle_at": now_iso(),
            "status": "waiting_for_agreement",
            "message": message,
            "exit_code": 0,
            "workflow_path": contract.path,
        }
        _runner_event(project_root, "cycle_skipped", "waiting_for_agreement", message)
        _refresh_dashboard(project_root, warning="", no_dashboard=no_dashboard)
        return result, True

    ok, hook_message = _run_hook(
        project_root,
        "before_cycle",
        contract.hooks_before_cycle,
        contract.hooks_timeout_sec,
    )
    if not ok:
        result = {
            "cycle_at": now_iso(),
            "status": "hook_failed",
            "message": hook_message,
            "exit_code": 1,
            "workflow_path": contract.path,
        }
        _runner_event(project_root, "cycle_failed", "hook_failed", hook_message)
        _refresh_dashboard(project_root, warning=hook_message, no_dashboard=no_dashboard)
        return result, True

    if contract.validation_run_plan_check:
        check_result = run_script("plan_check.py", ["--project", str(project_root)], check=False)
        if check_result.returncode != 0:
            message = _truncate((check_result.stdout or "") + "\n" + (check_result.stderr or ""))
            result = {
                "cycle_at": now_iso(),
                "status": "validation_failed",
                "message": message,
                "exit_code": 1,
                "workflow_path": contract.path,
            }
            _runner_event(project_root, "cycle_failed", "validation_failed", message)
            _refresh_dashboard(project_root, warning=message, no_dashboard=no_dashboard)
            return result, True

    if contract.orchestration_auto_refresh:
        refreshed, refresh_message = _refresh_orchestration(project_root)
        if not refreshed:
            result = {
                "cycle_at": now_iso(),
                "status": "orchestration_failed",
                "message": refresh_message,
                "exit_code": 1,
                "workflow_path": contract.path,
            }
            _runner_event(project_root, "cycle_failed", "orchestration_failed", refresh_message)
            _refresh_dashboard(project_root, warning=refresh_message, no_dashboard=no_dashboard)
            return result, True

    groups = _runnable_groups(project_root)
    if not groups:
        message = "no runnable work items"
        result = {
            "cycle_at": now_iso(),
            "status": "idle",
            "message": message,
            "exit_code": 0,
            "workflow_path": contract.path,
        }
        _runner_event(project_root, "cycle_skipped", "idle", message)
        ok_after, after_message = _run_hook(
            project_root,
            "after_cycle",
            contract.hooks_after_cycle,
            contract.hooks_timeout_sec,
        )
        warning = "" if ok_after else after_message
        _refresh_dashboard(project_root, warning=warning, no_dashboard=no_dashboard)
        return result, True

    dispatch_rc, dispatch_message = _run_dispatch(project_root, contract, no_dashboard=no_dashboard)
    cycle_status = "dispatched" if dispatch_rc == 0 else "dispatch_failed"
    _runner_event(
        project_root,
        "cycle_completed" if dispatch_rc == 0 else "cycle_failed",
        cycle_status,
        dispatch_message or cycle_status,
        runnable_groups=len(groups),
        runnable_jobs=sum(len(group) for group in groups),
    )

    ok_after, after_message = _run_hook(
        project_root,
        "after_cycle",
        contract.hooks_after_cycle,
        contract.hooks_timeout_sec,
    )
    warning = "" if ok_after else after_message
    _refresh_dashboard(project_root, warning=warning, no_dashboard=no_dashboard)
    result = {
        "cycle_at": now_iso(),
        "status": cycle_status,
        "message": dispatch_message,
        "exit_code": 0 if dispatch_rc == 0 else dispatch_rc,
        "workflow_path": contract.path,
        "runnable_groups": len(groups),
        "runnable_jobs": sum(len(group) for group in groups),
    }
    return result, True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run TheWorkshop as a Symphony-style local project runner.")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--workflow", help="Explicit WORKFLOW.md path (default: <project>/WORKFLOW.md)")
    parser.add_argument("--interval-sec", type=float, default=0.0, help="Override polling interval seconds")
    parser.add_argument("--max-cycles", type=int, default=0, help="Max cycles before exit (0 = unlimited)")
    parser.add_argument("--max-seconds", type=int, default=0, help="Max runtime before exit (0 = unlimited)")
    parser.add_argument("--once", action="store_true", help="Run a single cycle and exit")
    parser.add_argument("--detach", action="store_true", help="Run in background and exit immediately")
    parser.add_argument("--pid-file", default="", help="PID file path (default: <project>/tmp/workflow-runner.json)")
    parser.add_argument("--log-file", default="", help="Log path for detach mode (default: <project>/tmp/workflow-runner.log)")
    parser.add_argument("--no-dashboard", action="store_true", help="Skip dashboard refresh after each cycle")
    args = parser.parse_args(argv)

    project_root = resolve_project_root(args.project)
    pid_file = Path(args.pid_file).expanduser() if args.pid_file else _state_path(project_root)
    if not pid_file.is_absolute():
        pid_file = (project_root / pid_file).resolve()
    log_file = Path(args.log_file).expanduser() if args.log_file else (project_root / "tmp" / "workflow-runner.log")
    if not log_file.is_absolute():
        log_file = (project_root / log_file).resolve()

    if args.detach:
        return _detach_self(project_root, args, pid_file=pid_file, log_file=log_file)

    if pid_file.exists():
        state = _load_json(pid_file)
        pid = int(state.get("pid") or 0)
        if _pid_alive(pid):
            return 0

    max_cycles = 1 if args.once else int(args.max_cycles or 0)
    start_time = time.time()
    cycle_count = 0
    last_result: dict[str, Any] = {}
    default_interval = float(args.interval_sec or 0) or 30.0

    _write_json(
        pid_file,
        {
            "schema": "theworkshop.workflow-runner.v1",
            "pid": os.getpid(),
            "started_at": now_iso(),
            "project": str(project_root),
            "workflow_path": str(args.workflow or project_root / "WORKFLOW.md"),
            "status": "starting",
            "cycle_count": 0,
            "interval_sec": default_interval,
        },
    )

    try:
        while True:
            cycle_count += 1
            last_result, should_continue = _cycle(project_root, args.workflow, no_dashboard=args.no_dashboard)
            interval = default_interval
            try:
                contract = load_workflow_contract(project_root, workflow_path=args.workflow, missing_ok=True)
                if contract is not None and not args.interval_sec:
                    interval = float(contract.polling_interval_sec)
            except Exception:
                interval = default_interval

            state_payload = {
                "schema": "theworkshop.workflow-runner.v1",
                "pid": os.getpid(),
                "started_at": _load_json(pid_file).get("started_at") or now_iso(),
                "project": str(project_root),
                "workflow_path": str(last_result.get("workflow_path") or args.workflow or project_root / "WORKFLOW.md"),
                "status": str(last_result.get("status") or "unknown"),
                "last_message": str(last_result.get("message") or ""),
                "last_cycle_at": str(last_result.get("cycle_at") or now_iso()),
                "cycle_count": cycle_count,
                "interval_sec": interval,
            }
            _write_json(pid_file, state_payload)

            if not should_continue:
                break
            if max_cycles > 0 and cycle_count >= max_cycles:
                break
            if args.max_seconds > 0 and (time.time() - start_time) >= float(args.max_seconds):
                break
            time.sleep(max(0.25, interval))
    finally:
        final_state = {
            "schema": "theworkshop.workflow-runner.v1",
            "pid": 0,
            "started_at": _load_json(pid_file).get("started_at") or now_iso(),
            "project": str(project_root),
            "workflow_path": str(last_result.get("workflow_path") or args.workflow or project_root / "WORKFLOW.md"),
            "status": "stopped",
            "last_status": str(last_result.get("status") or "unknown"),
            "last_message": str(last_result.get("message") or ""),
            "last_cycle_at": str(last_result.get("cycle_at") or now_iso()),
            "cycle_count": cycle_count,
            "interval_sec": interval if "interval" in locals() else default_interval,
            "stopped_at": now_iso(),
        }
        _write_json(pid_file, final_state)

    if args.once and int(last_result.get("exit_code") or 0) != 0:
        return int(last_result.get("exit_code") or 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
