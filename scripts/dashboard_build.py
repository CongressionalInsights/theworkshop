#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from twlib import (
    build_token_cost_payload,
    format_duration,
    list_job_dirs,
    list_workstream_dirs,
    load_job,
    load_workstream,
    now_iso,
    parse_time,
    read_md,
    resolve_project_root,
)


def read_execution_stats(project_root: Path) -> dict:
    path = project_root / "logs" / "execution.jsonl"
    if not path.exists():
        return {"commands": 0, "failures": 0, "avg_duration_sec": 0.0}
    entries = []
    for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not ln.strip():
            continue
        try:
            entries.append(json.loads(ln))
        except Exception:
            continue
    total = len(entries)
    failures = sum(1 for e in entries if int(e.get("exit_code", 0)) != 0)
    durs = [int(e.get("duration_sec", 0)) for e in entries]
    avg = float(sum(durs) / len(durs)) if durs else 0.0
    return {"commands": total, "failures": failures, "avg_duration_sec": avg}


def read_rewards(project_root: Path) -> dict[str, dict]:
    p = project_root / "outputs" / "rewards.json"
    if not p.exists():
        return {}
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict[str, dict] = {}
    for item in payload.get("jobs", []) or []:
        wi = str(item.get("work_item_id") or "")
        if wi:
            out[wi] = item
    return out


def elapsed_since(started_at: str) -> str:
    dt = parse_time(started_at or "")
    if not dt:
        return "n/a"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return format_duration((now - dt).total_seconds())


def truncate_text(value: str, *, limit: int = 120) -> str:
    text = str(value or "").strip().replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def short_id(value: Any, *, keep: int = 8) -> str:
    token = str(value or "").strip()
    if not token:
        return ""
    return token if len(token) <= keep else token[:keep]


def short_wi_id(value: Any) -> str:
    token = str(value or "").strip()
    if not token:
        return "WI-???"
    match = re.search(r"\bWI-\d{8}-(\d+)\b", token)
    if match:
        return f"WI-{match.group(1).zfill(3)}"
    if token.startswith("WI-"):
        tail = token.split("-")[-1]
        if tail.isdigit():
            return f"WI-{tail.zfill(3)}"
        return token
    return token


def build_work_item_index(workstreams: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for ws in workstreams:
        ws_id = str(ws.get("id") or "").strip()
        ws_title = str(ws.get("title") or "").strip()
        for job in ws.get("jobs") or []:
            if not isinstance(job, dict):
                continue
            wi = str(job.get("work_item_id") or "").strip()
            if not wi:
                continue
            out[wi] = {
                "title": str(job.get("title") or "").strip(),
                "ws_id": ws_id,
                "ws_title": ws_title,
                "wi_short": short_wi_id(wi),
            }
    return out


def normalize_event_phrase(value: Any) -> str:
    token = str(value or "").strip()
    if not token:
        return ""
    token = token.replace("_", " ").replace("-", " ")
    token = re.sub(r"\s+", " ", token).strip()
    token = re.sub(r"\b(\w+)\s+\1\b", r"\1", token, flags=re.IGNORECASE)
    return token.lower()


def normalize_message_for_display(message: Any, wi_id: str, wi_short: str) -> str:
    text = str(message or "").strip()
    if not text:
        return ""
    if wi_id:
        text = text.replace(wi_id, wi_short)
    text = re.sub(r"\b(active|completed|failed|blocked)\s+\1\b", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" -:\t")
    return truncate_text(text, limit=160)


def humanize_subagent_event(evt: dict[str, Any], wi_index: dict[str, dict[str, str]]) -> dict[str, Any]:
    wi_id = str(evt.get("work_item_id") or "").strip()
    wi_meta = wi_index.get(wi_id) or {}
    wi_short = short_wi_id(wi_id) if wi_id else "WI-???"
    wi_title = str(wi_meta.get("title") or "").strip()
    if wi_title:
        display_work_item = f"{wi_title} ({wi_short})"
    elif wi_id:
        display_work_item = wi_short
    else:
        display_work_item = "Unlinked task"

    source = normalize_subagent_source(evt.get("source"))
    agent_type = str(evt.get("agent_type") or "worker").strip().lower()
    agent_short = short_id(evt.get("agent_id"))
    display_actor = f"{source} {agent_type}"
    if agent_short:
        display_actor += f" #{agent_short}"

    status_raw = str(evt.get("status") or "").strip()
    status = classify_subagent_status(status_raw) or normalize_event_phrase(status_raw) or "updated"
    if status == "active":
        status_word = "started"
    elif status in {"completed", "failed", "blocked"}:
        status_word = status
    else:
        status_word = "updated"

    message = normalize_message_for_display(evt.get("message"), wi_id, wi_short)
    base = f"{display_work_item} {status_word}"
    if message:
        display_text = f"{base} - {message} ({display_actor})"
    else:
        display_text = f"{base} ({display_actor})"
    verb = {
        "started": "Started",
        "completed": "Completed",
        "failed": "Failed",
        "blocked": "Blocked",
        "updated": "Updated",
    }.get(status_word, "Updated")
    if wi_title:
        ticker_subject = f"{wi_short}: {truncate_text(wi_title, limit=44)}"
    elif wi_id:
        ticker_subject = wi_short
    else:
        ticker_subject = "Unlinked task"
    ticker_text = f"{verb}: {ticker_subject}"
    if message:
        ticker_text = truncate_text(f"{ticker_text} - {truncate_text(message, limit=56)}", limit=90)

    severity = "info"
    if status == "failed":
        severity = "error"
    elif status == "blocked":
        severity = "warn"

    raw_payload = evt.get("raw")
    if not isinstance(raw_payload, dict):
        raw_payload = dict(evt)

    return {
        **evt,
        "display_text": display_text,
        "ticker_text": ticker_text,
        "display_actor": display_actor,
        "display_work_item": display_work_item,
        "display_severity": severity,
        "raw": raw_payload,
    }


def humanize_dispatch_summary(summary: dict[str, Any]) -> str:
    if not isinstance(summary, dict):
        return ""
    keys = {"group_count", "job_count", "completed", "simulated", "failed_or_blocked"}
    if not any(key in summary for key in keys):
        return ""
    groups = int(summary.get("group_count") or 0)
    jobs = int(summary.get("job_count") or 0)
    completed = int(summary.get("completed") or 0)
    simulated = int(summary.get("simulated") or 0)
    failed_or_blocked = int(summary.get("failed_or_blocked") or 0)
    return (
        f"{groups} group{'s' if groups != 1 else ''} executed, "
        f"{jobs} job{'s' if jobs != 1 else ''} run, "
        f"{completed} completed, {simulated} simulated, "
        f"{failed_or_blocked} failed/blocked"
    )


def normalize_truth_status(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"pass", "passed", "ok", "success", "succeeded", "green"}:
        return "pass"
    if raw in {"fail", "failed", "error", "red"}:
        return "fail"
    return "unknown"


def truth_failure_text(item: Any) -> str:
    if item is None:
        return ""
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, (int, float)):
        return str(item)
    if isinstance(item, dict):
        for key in ("message", "reason", "error", "summary", "detail", "check"):
            value = str(item.get(key) or "").strip()
            if value:
                return value
        try:
            return json.dumps(item, sort_keys=True)
        except Exception:
            return str(item)
    if isinstance(item, list):
        out = [truth_failure_text(v) for v in item]
        out = [v for v in out if v]
        return "; ".join(out)
    return str(item)


def normalize_truth_failures(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        out = [truth_failure_text(v) for v in value]
        return [v for v in out if v]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
            except Exception:
                parsed = None
            if isinstance(parsed, list):
                out = [truth_failure_text(v) for v in parsed]
                return [v for v in out if v]
        return [text]
    return [truth_failure_text(value)] if truth_failure_text(value) else []


def collect_truth_for_job(job_dir: Path) -> tuple[str, list[str], str]:
    plan_doc = read_md(job_dir / "plan.md")
    status = normalize_truth_status(plan_doc.frontmatter.get("truth_last_status"))
    failures = normalize_truth_failures(plan_doc.frontmatter.get("truth_last_failures"))
    snippet = truncate_text(failures[-1], limit=140) if failures else ""
    return status, failures, snippet


def classify_subagent_status(value: str) -> str | None:
    token = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not token:
        return None
    if "block" in token:
        return "blocked"
    if any(k in token for k in ("fail", "error", "cancel", "timeout")):
        return "failed"
    if any(k in token for k in ("complete", "done", "success", "pass", "finish")):
        return "completed"
    if any(k in token for k in ("active", "running", "in_progress", "start", "spawn", "queue", "dispatch", "launch")):
        return "active"
    return None


def parse_subagent_event(entry: dict[str, Any]) -> tuple[str | None, str]:
    for key in ("status", "state", "result", "event", "type", "action"):
        value = entry.get(key)
        if value is None:
            continue
        status = classify_subagent_status(str(value))
        if status:
            return status, str(value)
    return None, ""


def _load_jsonl_dicts(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not path.exists():
        return out
    for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not ln.strip():
            continue
        try:
            entry = json.loads(ln)
        except Exception:
            continue
        if isinstance(entry, dict):
            out.append(entry)
    return out


def normalize_subagent_source(value: Any) -> str:
    token = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if token in {"dispatch", "manual", "external"}:
        return token
    if "dispatch" in token:
        return "dispatch"
    if "external" in token:
        return "external"
    return "manual"


def _summarize_subagent_entries(
    entries: list[dict[str, Any]],
    *,
    recent_limit: int,
    source_filter: str | None = None,
    include_blocked: bool = False,
) -> tuple[dict[str, int], list[dict[str, str]]]:
    latest_by_agent: dict[str, str] = {}
    parsed_events: list[dict[str, str]] = []
    source_filter_norm = normalize_subagent_source(source_filter) if source_filter else ""

    for idx, entry in enumerate(entries):
        status, raw_event = parse_subagent_event(entry)
        source = normalize_subagent_source(entry.get("source"))
        if source_filter_norm and source != source_filter_norm:
            continue
        agent_id = str(
            entry.get("agent_id")
            or entry.get("subagent_id")
            or entry.get("agent")
            or entry.get("worker_id")
            or entry.get("work_item_id")
            or f"event-{idx}"
        )
        if status:
            latest_by_agent[agent_id] = status

        message = str(
            entry.get("message")
            or entry.get("summary")
            or entry.get("detail")
            or entry.get("error")
            or ""
        ).strip()
        parsed_events.append(
            {
                "timestamp": str(entry.get("timestamp") or entry.get("at") or entry.get("time") or ""),
                "agent_id": agent_id,
                "agent_type": str(entry.get("agent_type") or ""),
                "work_item_id": str(entry.get("work_item_id") or ""),
                "event": raw_event or str(entry.get("event") or ""),
                "status": status or "unknown",
                "source": source,
                "dispatch_run_id": str(entry.get("dispatch_run_id") or ""),
                "group_index": str(entry.get("group_index") or ""),
                "message": truncate_text(message, limit=160),
                "raw": entry,
            }
        )

    counts: dict[str, int] = {
        "active": sum(1 for s in latest_by_agent.values() if s == "active"),
        "completed": sum(1 for s in latest_by_agent.values() if s == "completed"),
        "failed": sum(1 for s in latest_by_agent.values() if s == "failed"),
    }
    if include_blocked:
        counts["blocked"] = sum(1 for s in latest_by_agent.values() if s == "blocked")
    recent_events = parsed_events[-recent_limit:] if parsed_events else []
    return counts, recent_events


def read_subagents(project_root: Path, *, recent_limit: int = 12) -> dict:
    subagents, _ = read_subagent_telemetry(project_root, recent_limit=recent_limit)
    return subagents


def read_dispatch(project_root: Path, *, recent_limit: int = 12) -> dict:
    _, dispatch = read_subagent_telemetry(project_root, recent_limit=recent_limit)
    return dispatch


def read_subagent_telemetry(project_root: Path, *, recent_limit: int = 12) -> tuple[dict, dict]:
    path = project_root / "logs" / "agents.jsonl"
    dispatch_log = project_root / "logs" / "subagent-dispatch.jsonl"
    execution_path = project_root / "outputs" / "orchestration-execution.json"
    agent_entries = _load_jsonl_dicts(path)
    dispatch_entries = _load_jsonl_dicts(dispatch_log)
    canonical_entries: list[dict[str, Any]] = []
    subagents_path = path
    subagents_note = ""
    dispatch_mode = "not_used"

    if agent_entries:
        canonical_entries = agent_entries
        has_dispatch_events = any(
            normalize_subagent_source(entry.get("source")) == "dispatch"
            for entry in canonical_entries
        )
        dispatch_mode = "active" if has_dispatch_events else "not_used"
    elif dispatch_entries:
        canonical_entries = [{**entry, "source": "dispatch"} for entry in dispatch_entries]
        subagents_path = dispatch_log
        subagents_note = "derived from legacy dispatch log (agents log missing)."
        dispatch_mode = "legacy_fallback"

    if canonical_entries:
        sub_counts, sub_recent_events = _summarize_subagent_entries(canonical_entries, recent_limit=recent_limit)
    else:
        sub_counts, sub_recent_events = ({"active": 0, "completed": 0, "failed": 0}, [])

    if canonical_entries:
        dispatch_counts, dispatch_recent_events = _summarize_subagent_entries(
            canonical_entries,
            recent_limit=recent_limit,
            source_filter="dispatch",
            include_blocked=True,
        )
    else:
        dispatch_counts, dispatch_recent_events = ({"active": 0, "completed": 0, "failed": 0, "blocked": 0}, [])

    dispatch_note = ""
    if dispatch_mode == "not_used":
        dispatch_note = "dispatch engine not used in this run."
    elif dispatch_mode == "legacy_fallback":
        dispatch_note = "dispatch counts derived from legacy dispatch log."
    elif dispatch_mode == "active" and not dispatch_log.exists():
        dispatch_note = "dispatch counts derived from canonical agent telemetry."

    if not canonical_entries:
        subagents = {
            "present": False,
            "path": str(path.relative_to(project_root)),
            "counts": {"active": 0, "completed": 0, "failed": 0},
            "recent_events": [],
            "telemetry_note": "No sub-agent telemetry found. Use `theworkshop dispatch` or `theworkshop agent-log`/`theworkshop agent-closeout` when delegating manually.",
        }
    else:
        subagents = {
            "present": True,
            "path": str(subagents_path.relative_to(project_root)),
            "counts": sub_counts,
            "recent_events": sub_recent_events,
            "telemetry_note": subagents_note,
        }

    execution = {}
    if execution_path.exists():
        try:
            payload = json.loads(execution_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                execution = payload
        except Exception:
            execution = {}

    dispatch = {
        "present": dispatch_mode != "not_used" or dispatch_log.exists() or execution_path.exists(),
        "path": str(dispatch_log.relative_to(project_root)),
        "execution_path": str(execution_path.relative_to(project_root)),
        "counts": dispatch_counts,
        "recent_events": dispatch_recent_events,
        "execution": execution if isinstance(execution, dict) else {},
        "mode": dispatch_mode,
        "telemetry_note": dispatch_note,
    }
    return subagents, dispatch


def normalize_group_members(value: Any) -> list[str]:
    if isinstance(value, list):
        out = [str(v).strip() for v in value if str(v).strip()]
        return out
    if isinstance(value, tuple):
        out = [str(v).strip() for v in value if str(v).strip()]
        return out
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, dict):
        for key in ("jobs", "work_items", "items", "members", "nodes", "ids"):
            members = value.get(key)
            if isinstance(members, (list, tuple)):
                out = [str(v).strip() for v in members if str(v).strip()]
                if out:
                    return out
        single = str(value.get("id") or value.get("work_item_id") or "").strip()
        return [single] if single else []
    return []


def normalize_parallel_groups(value: Any) -> list[list[str]]:
    if not isinstance(value, list):
        return []
    out: list[list[str]] = []
    for group in value:
        members = normalize_group_members(group)
        if members:
            out.append(members)
    return out


def normalize_path_list(value: Any) -> list[str]:
    if isinstance(value, list):
        out = [str(v).strip() for v in value if str(v).strip()]
        return out
    if isinstance(value, dict):
        for key in ("jobs", "work_items", "items", "nodes", "ids"):
            members = value.get(key)
            if isinstance(members, list):
                out = [str(v).strip() for v in members if str(v).strip()]
                if out:
                    return out
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    return []


def read_orchestration(project_root: Path) -> dict:
    path = project_root / "outputs" / "orchestration.json"
    default = {
        "present": False,
        "path": str(path.relative_to(project_root)),
        "parallel_groups": [],
        "critical_path": [],
        "critical_path_hours": 0.0,
        "stale_dependency_count": 0,
    }
    if not path.exists():
        return default

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

    if not isinstance(raw, dict):
        return default

    groups_value = None
    for key in ("parallel_groups", "groups", "execution_groups", "batches", "waves"):
        if key in raw:
            groups_value = raw.get(key)
            break
    if groups_value is None and isinstance(raw.get("orchestration"), dict):
        nested = raw["orchestration"]
        for key in ("parallel_groups", "groups", "execution_groups", "batches", "waves"):
            if key in nested:
                groups_value = nested.get(key)
                break
    parallel_groups = normalize_parallel_groups(groups_value)

    critical_path_value: Any = None
    for key in ("critical_path", "criticalPath", "critical_path_jobs"):
        if key in raw:
            critical_path_value = raw.get(key)
            break
    if critical_path_value is None and isinstance(raw.get("critical_path"), dict):
        critical_path_value = raw.get("critical_path")
    if critical_path_value is None and isinstance(raw.get("summary"), dict):
        summary = raw["summary"]
        for key in ("critical_path", "criticalPath", "critical_path_jobs"):
            if key in summary:
                critical_path_value = summary.get(key)
                break
    critical_path = normalize_path_list(critical_path_value)

    critical_hours = 0.0
    for key in ("critical_path_hours", "criticalPathHours", "hours"):
        if key in raw:
            try:
                critical_hours = float(raw.get(key) or 0.0)
            except Exception:
                critical_hours = 0.0
            break
    if critical_hours <= 0 and isinstance(raw.get("critical_path"), dict):
        for key in ("hours", "total_hours"):
            if key in raw["critical_path"]:
                try:
                    critical_hours = float(raw["critical_path"].get(key) or 0.0)
                except Exception:
                    critical_hours = 0.0
                break

    stale_count = 0
    stale_raw = raw.get("stale_dependencies")
    if isinstance(stale_raw, list):
        stale_count = len(stale_raw)
    elif isinstance(stale_raw, dict):
        stale_count = len(stale_raw.keys())
    for key in ("stale_dependency_count", "stale_dependencies_count", "stale_count"):
        if key in raw:
            try:
                stale_count = int(raw.get(key) or 0)
            except Exception:
                stale_count = 0
            break

    if stale_count <= 0:
        inv_path = project_root / "outputs" / "invalidation-report.json"
        if inv_path.exists():
            try:
                inv = json.loads(inv_path.read_text(encoding="utf-8"))
                counts = inv.get("counts") if isinstance(inv, dict) else {}
                if isinstance(counts, dict):
                    stale_count = int(counts.get("stale_jobs") or 0)
            except Exception:
                stale_count = stale_count

    return {
        "present": True,
        "path": str(path.relative_to(project_root)),
        "parallel_groups": parallel_groups,
        "critical_path": critical_path,
        "critical_path_hours": critical_hours,
        "stale_dependency_count": stale_count,
    }


def build_payload(project_root: Path) -> dict:
    proj_doc = read_md(project_root / "plan.md")
    pfm = proj_doc.frontmatter
    ts = now_iso()

    workstreams = []
    jobs_all = []
    rewards = read_rewards(project_root)

    for ws_dir in list_workstream_dirs(project_root):
        ws = load_workstream(ws_dir)
        ws_jobs = []
        for job_dir in list_job_dirs(ws_dir):
            j = load_job(job_dir)
            reward = rewards.get(j.work_item_id, {})
            truth_status, truth_failures, truth_failure_snippet = collect_truth_for_job(job_dir)
            ws_jobs.append(
                {
                    "work_item_id": j.work_item_id,
                    "title": j.title,
                    "status": j.status,
                    "wave_id": j.wave_id,
                    "depends_on": j.depends_on,
                    "loop_enabled": j.loop_enabled,
                    "loop_mode": j.loop_mode,
                    "loop_max_iterations": j.loop_max_iterations,
                    "loop_target_promise": j.loop_target_promise,
                    "loop_status": j.loop_status,
                    "loop_last_attempt": j.loop_last_attempt,
                    "loop_last_started_at": j.loop_last_started_at,
                    "loop_last_stopped_at": j.loop_last_stopped_at,
                    "loop_stop_reason": j.loop_stop_reason,
                    "reward_target": j.reward_target,
                    "reward_score": int(reward.get("reward_score", j.reward_last_score)),
                    "reward_next_action": str(reward.get("next_action", j.reward_last_next_action)),
                    "truth_status": truth_status,
                    "truth_last_failures": truth_failures,
                    "truth_last_failure_snippet": truth_failure_snippet,
                    "path": str(job_dir.relative_to(project_root)),
                }
            )
        workstreams.append(
            {
                "id": ws.id,
                "title": ws.title,
                "status": ws.status,
                "depends_on": ws.depends_on,
                "path": str(ws_dir.relative_to(project_root)),
                "jobs": ws_jobs,
            }
        )
        jobs_all.extend(ws_jobs)

    orchestration = read_orchestration(project_root)
    subagents, dispatch = read_subagent_telemetry(project_root)
    wi_index = build_work_item_index(workstreams)
    truth_summary = {
        "pass": sum(1 for j in jobs_all if j.get("truth_status") == "pass"),
        "fail": sum(1 for j in jobs_all if j.get("truth_status") == "fail"),
        "unknown": sum(1 for j in jobs_all if j.get("truth_status") == "unknown"),
        "stale_dependency_count": int(orchestration.get("stale_dependency_count") or 0),
    }

    stats = {
        "workstreams_total": len(workstreams),
        "jobs_total": len(jobs_all),
        "jobs_status": {
            "planned": sum(1 for j in jobs_all if j["status"] == "planned"),
            "in_progress": sum(1 for j in jobs_all if j["status"] == "in_progress"),
            "blocked": sum(1 for j in jobs_all if j["status"] == "blocked"),
            "done": sum(1 for j in jobs_all if j["status"] == "done"),
            "cancelled": sum(1 for j in jobs_all if j["status"] == "cancelled"),
        },
        "loops_enabled": sum(1 for j in jobs_all if bool(j.get("loop_enabled"))),
        "loops_active": sum(1 for j in jobs_all if str(j.get("loop_status") or "") == "active"),
        "loops_completed": sum(1 for j in jobs_all if str(j.get("loop_status") or "") == "completed"),
        "loops_blocked": sum(1 for j in jobs_all if str(j.get("loop_status") or "") == "blocked"),
        "loops_stopped": sum(1 for j in jobs_all if str(j.get("loop_status") or "") == "stopped"),
        "loops_error": sum(1 for j in jobs_all if str(j.get("loop_status") or "") == "error"),
    }

    tokens_payload = build_token_cost_payload(project_root, "codex")
    sub_recent_raw = subagents.get("recent_events") if isinstance(subagents.get("recent_events"), list) else []
    subagents["recent_events"] = [humanize_subagent_event(evt, wi_index) for evt in sub_recent_raw if isinstance(evt, dict)]

    dispatch_recent_raw = dispatch.get("recent_events") if isinstance(dispatch.get("recent_events"), list) else []
    dispatch["recent_events"] = [humanize_subagent_event(evt, wi_index) for evt in dispatch_recent_raw if isinstance(evt, dict)]
    dispatch_summary = dispatch.get("execution")
    summary_obj = dispatch_summary.get("summary") if isinstance(dispatch_summary, dict) else {}
    dispatch["display_summary"] = humanize_dispatch_summary(summary_obj if isinstance(summary_obj, dict) else {})

    by_wi = tokens_payload.get("by_work_item")
    if isinstance(by_wi, list):
        mapped_rows: list[dict[str, Any]] = []
        for row in by_wi:
            if not isinstance(row, dict):
                continue
            mapped = dict(row)
            wi_id = str(mapped.get("work_item_id") or "").strip()
            wi_meta = wi_index.get(wi_id) or {}
            wi_short = short_wi_id(wi_id) if wi_id else "WI-???"
            title = str(wi_meta.get("title") or "").strip()
            mapped["display_work_item"] = f"{title} ({wi_short})" if title else wi_short if wi_id else "Unlinked task"
            mapped_rows.append(mapped)
        tokens_payload = {**tokens_payload, "by_work_item": mapped_rows}

    gh_enabled = bool(pfm.get("github_enabled"))
    gh_repo = str(pfm.get("github_repo") or "")
    gh_map_path = project_root / "notes" / "github-map.json"
    gh_sync = {"enabled": gh_enabled, "repo": gh_repo, "last_sync_at": ""}
    if gh_map_path.exists():
        try:
            gh = json.loads(gh_map_path.read_text(encoding="utf-8"))
            gh_sync["last_sync_at"] = str(gh.get("last_sync_at") or "")
            if not gh_sync["repo"]:
                gh_sync["repo"] = str(gh.get("repo") or "")
        except Exception:
            pass

    payload = {
        "schema": "theworkshop.dashboard.v1",
        "generated_at": ts,
        "project": {
            "id": str(pfm.get("id") or ""),
            "title": str(pfm.get("title") or ""),
            "status": str(pfm.get("status") or ""),
            "started_at": str(pfm.get("started_at") or ""),
            "elapsed": elapsed_since(str(pfm.get("started_at") or "")),
            "agreement_status": str(pfm.get("agreement_status") or ""),
            "waves": pfm.get("waves", []) or [],
        },
        "stats": stats,
        "execution_logs": read_execution_stats(project_root),
        "tokens": tokens_payload,
        "github_sync": gh_sync,
        "workstreams": workstreams,
        "truth_summary": truth_summary,
        "orchestration": orchestration,
        "subagents": subagents,
        "dispatch": dispatch,
    }
    return payload


def html_escape(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def status_class(status: str) -> str:
    return {
        "planned": "st-planned",
        "in_progress": "st-inprogress",
        "blocked": "st-blocked",
        "done": "st-done",
        "cancelled": "st-cancelled",
    }.get(status, "st-planned")


def loop_status_class(status: str) -> str:
    return {
        "active": "st-inprogress",
        "completed": "st-done",
        "blocked": "st-blocked",
        "error": "st-cancelled",
        "stopped": "st-cancelled",
    }.get(status, "st-planned")


def truth_class(status: str) -> str:
    return {
        "pass": "truth-pass",
        "fail": "truth-fail",
        "unknown": "truth-unknown",
    }.get(str(status or "").strip().lower(), "truth-unknown")


def _render_dashboard_css() -> str:
    return """
:root {
  --bg: #eef3f1;
  --bg-hi: #f7faf9;
  --panel: rgba(251, 253, 252, 0.96);
  --panel-solid: #fbfdfc;
  --surface: #f3f7f5;
  --ink: #12202b;
  --muted: #5f6c77;
  --line: #d4dee2;
  --line-strong: #b9c9cf;
  --accent: #0a6a63;
  --accent-soft: rgba(10, 106, 99, 0.1);
  --risk: #a5372f;
  --risk-soft: rgba(165, 55, 47, 0.14);
  --planned: #6b7280;
  --inprogress: #b45f06;
  --blocked: #b42318;
  --done: #027a48;
  --cancelled: #7a1f5c;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; min-height: 100vh; }
body {
  font-family: "IBM Plex Sans", "Avenir Next", "Segoe UI", Helvetica, Arial, sans-serif;
  color: var(--ink);
  background:
    radial-gradient(circle at 14% 10%, rgba(202, 223, 217, 0.72) 0%, transparent 34%),
    radial-gradient(circle at 86% 0%, rgba(221, 231, 241, 0.85) 0%, transparent 32%),
    linear-gradient(rgba(32, 57, 74, 0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(32, 57, 74, 0.03) 1px, transparent 1px),
    linear-gradient(180deg, var(--bg-hi) 0%, var(--bg) 72%);
  background-size: 100% 100%, 100% 100%, 48px 48px, 48px 48px, 100% 100%;
}
.wrap {
  max-width: 1460px;
  margin: 0 auto;
  padding: 22px 20px 32px;
}
h1 { margin: 0; font-size: 34px; letter-spacing: -.02em; }
h2 { margin: 20px 0 10px; font-size: 20px; letter-spacing: -.01em; }
h3 { margin: 0 0 8px; font-size: 16px; letter-spacing: .01em; }
h4 { margin: 0; font-size: 12px; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); }
p { margin: 6px 0; }
ul { margin: 8px 0 0 18px; }
code {
  background: #f4f7f8;
  border: 1px solid #dbe5e8;
  border-radius: 6px;
  padding: 2px 6px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, monospace;
  font-size: 12px;
}
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, monospace; }
.mono, code, .chip-count, .metric .value, .summary-stat b { font-variant-numeric: tabular-nums; }
.muted { color: var(--muted); }
.card {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 16px;
  box-shadow: 0 1px 0 rgba(255,255,255,0.8), 0 10px 24px rgba(16, 29, 38, 0.04);
  animation: cardIn .22s cubic-bezier(0.25, 1, 0.5, 1) both;
}
@keyframes cardIn {
  from { opacity: 0; transform: translateY(8px); }
  to { opacity: 1; transform: translateY(0); }
}
.monitor {
  position: sticky;
  top: 12px;
  z-index: 25;
  margin: 0 0 12px;
  padding: 12px 16px;
  border-radius: 12px;
  border: 1px solid var(--line-strong);
  background: rgba(248, 252, 251, 0.96);
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}
.monitor .group {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}
.badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: var(--surface);
  font-size: 12px;
  line-height: 1.6;
}
.badge-on { border-color: rgba(10,106,99,0.35); background: rgba(10,106,99,0.10); }
.badge-off { border-color: rgba(95,107,117,0.35); background: rgba(95,107,117,0.10); }
.badge-frozen {
  border-color: rgba(122, 31, 92, 0.35);
  background: rgba(122, 31, 92, 0.10);
  color: var(--cancelled);
}
.badge-offline {
  border-color: rgba(180, 35, 24, 0.35);
  background: rgba(180, 35, 24, 0.10);
  color: var(--blocked);
}
.badge-stale {
  border-color: rgba(180,35,24,0.35);
  background: rgba(180,35,24,0.10);
  color: var(--blocked);
  font-weight: 700;
  letter-spacing: .04em;
}
button, .btn {
  appearance: none;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 6px 10px;
  background: var(--panel-solid);
  color: var(--ink);
  font-size: 12px;
  line-height: 1.2;
  cursor: pointer;
  transition: border-color .18s ease, background-color .18s ease, transform .12s ease, color .18s ease;
}
button:hover, .btn:hover { border-color: rgba(10,106,99,0.45); background: #fff; }
button:active, .btn:active { transform: translateY(1px); }
button:focus-visible, .btn:focus-visible, input:focus-visible {
  outline: 2px solid rgba(10,106,99,0.28);
  outline-offset: 2px;
}
.hero {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(280px, 0.8fr);
  gap: 12px;
  margin-bottom: 12px;
}
.hero-title-row, .hero .project-line {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.hero-copy {
  max-width: 760px;
  font-size: 14px;
  color: var(--muted);
}
.hero-meta, .summary-grid {
  display: grid;
  gap: 10px;
}
.summary-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
.summary-card {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 12px;
}
.summary-kicker {
  font-size: 11px;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 6px;
}
.summary-stat b {
  display: block;
  font-size: 24px;
  line-height: 1.1;
  margin-bottom: 3px;
}
.summary-detail {
  color: var(--muted);
  font-size: 12px;
}
.pill {
  display: inline-block;
  padding: 3px 9px;
  border-radius: 999px;
  color: white;
  font-size: 12px;
  line-height: 1.5;
  vertical-align: middle;
}
.st-planned { background: var(--planned); }
.st-inprogress { background: var(--inprogress); }
.st-blocked { background: var(--blocked); }
.st-done { background: var(--done); }
.st-cancelled { background: var(--cancelled); }
.truth-pill {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  line-height: 1.5;
  text-transform: uppercase;
  letter-spacing: .03em;
  font-weight: 700;
}
.truth-pass { background: rgba(2, 122, 72, 0.14); color: #03543f; }
.truth-fail { background: rgba(180, 35, 24, 0.14); color: #9a2418; }
.truth-unknown { background: rgba(95, 107, 117, 0.14); color: #3f4a54; }
.command-bar {
  margin-bottom: 12px;
}
.command-grid {
  display: grid;
  grid-template-columns: minmax(260px, 1.4fr) minmax(300px, 1fr) auto;
  gap: 10px;
  align-items: center;
}
.query-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #fff;
  padding: 7px 10px;
}
.query-wrap input {
  width: 100%;
  border: 0;
  background: transparent;
  color: var(--ink);
  font-size: 14px;
}
.query-wrap .hint {
  font-size: 11px;
  color: var(--muted);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 1px 5px;
}
.focus-group, .filter-group {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
.focus-btn {
  border-radius: 999px;
  padding: 6px 10px;
  font-weight: 600;
}
.focus-btn.is-active {
  background: var(--accent);
  border-color: rgba(10,106,99,0.45);
  color: #fff;
}
.chip {
  border-radius: 999px;
  padding: 5px 10px;
  background: var(--panel-solid);
  border: 1px solid var(--line);
  font-size: 12px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.chip.is-on {
  border-color: rgba(10,106,99,0.42);
  background: var(--accent-soft);
}
.chip .chip-count {
  display: inline-block;
  min-width: 14px;
  text-align: right;
  color: var(--muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, monospace;
  font-size: 11px;
}
.execution-band {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 12px;
}
.execution-card {
  display: grid;
  gap: 10px;
  min-height: 180px;
}
.execution-card .value {
  font-size: 28px;
  line-height: 1.05;
  font-weight: 700;
  letter-spacing: -.02em;
}
.execution-card .value.risk { color: var(--risk); }
.focus-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: 8px;
}
.focus-list li {
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 10px 12px;
  background: var(--surface);
}
.focus-list .line-1 {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 4px;
}
.focus-list .line-2 {
  color: var(--muted);
  font-size: 12px;
}
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 12px;
}
.metric {
  background: linear-gradient(180deg, rgba(255,255,255,0.85), rgba(243,247,245,0.95));
}
.metric h3 { margin-bottom: 6px; font-size: 12px; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); }
.metric .value { font-size: 30px; line-height: 1.05; font-weight: 700; letter-spacing: -.03em; }
.metric .split { font-size: 12px; color: var(--muted); line-height: 1.45; }
.main-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.5fr) minmax(340px, 0.9fr);
  gap: 12px;
  align-items: start;
}
.primary-stack, .secondary-stack {
  display: grid;
  gap: 12px;
}
.triage-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.triage-head .legend {
  color: var(--muted);
  font-size: 12px;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
th, td {
  text-align: left;
  padding: 8px 6px;
  border-top: 1px solid var(--line);
  vertical-align: top;
}
th {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: .05em;
  color: var(--muted);
  position: sticky;
  top: 0;
  background: rgba(249, 252, 251, 0.98);
}
.queue-wrap {
  max-height: 360px;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #fff;
}
.queue-wrap tr[data-target-row] { cursor: pointer; }
.queue-wrap tr[data-target-row]:hover { background: rgba(10, 106, 99, 0.08); }
.flag-risk {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--risk-soft);
  color: var(--risk);
  font-weight: 700;
  font-size: 11px;
}
.ws-controls {
  display: flex;
  gap: 8px;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.ws-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 10px;
}
.ws-head .meta {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.ws-body {
  margin-top: 10px;
  max-height: 420px;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #fff;
}
.ws-toggle { font-weight: 600; }
.ws-summary {
  font-size: 12px;
  color: var(--muted);
}
tr.is-risk td:first-child { border-left: 3px solid rgba(165, 55, 47, 0.55); }
tr.row-focus { animation: rowFocusFlash 1.6s ease-out; }
@keyframes rowFocusFlash {
  0% { background: rgba(10, 106, 99, 0.2); }
  100% { background: transparent; }
}
.ws-flag {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 7px;
  border-radius: 999px;
  font-size: 11px;
  background: rgba(95, 107, 117, 0.14);
  color: #3f4a54;
}
.ws-flag.risk {
  background: var(--risk-soft);
  color: var(--risk);
}
.monitor-list {
  margin: 6px 0 0 16px;
}
.event-list {
  margin: 8px 0 0 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 8px;
}
.event-list-wrap {
  max-height: 260px;
  overflow: auto;
  overscroll-behavior: contain;
  padding-right: 4px;
}
[data-event-row] {
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
  padding: 8px 10px;
}
[data-event-summary] {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}
.event-pill {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 2px 8px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .02em;
  text-transform: uppercase;
}
.event-pill.info {
  color: #31506c;
  background: rgba(49, 80, 108, 0.12);
  border: 1px solid rgba(49, 80, 108, 0.25);
}
.event-pill.warn {
  color: #9d4f02;
  background: rgba(180, 95, 6, 0.13);
  border: 1px solid rgba(180, 95, 6, 0.28);
}
.event-pill.error {
  color: #9b2c24;
  background: rgba(165, 55, 47, 0.14);
  border: 1px solid rgba(165, 55, 47, 0.3);
}
[data-event-details] { margin-top: 6px; }
[data-event-details] summary {
  cursor: pointer;
  color: var(--muted);
  font-size: 12px;
}
[data-event-raw] {
  margin-top: 6px;
  max-height: 180px;
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #f7faf9;
  padding: 8px;
  font-size: 11px;
}
.live-strip {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
}
.live-label {
  display: inline-flex;
  align-items: center;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: .07em;
  text-transform: uppercase;
  color: var(--muted);
}
.live-scroll {
  overflow: auto;
  width: 100%;
}
.live-track {
  display: flex;
  gap: 8px;
  min-width: 100%;
  width: max-content;
  flex-wrap: wrap;
}
.live-item {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 7px 10px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--surface);
  font-size: 12px;
  white-space: normal;
}
.live-item .src {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .04em;
  text-transform: uppercase;
  color: #31506c;
}
.diagnostic-list {
  display: grid;
  gap: 8px;
}
.diagnostic-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 12px;
  padding: 8px 0;
  border-top: 1px solid var(--line);
}
.diagnostic-row:first-child {
  border-top: 0;
  padding-top: 0;
}
.kbd {
  font-size: 10px;
  border: 1px solid var(--line);
  border-radius: 5px;
  padding: 1px 5px;
  color: var(--muted);
  background: #fff;
}
@media (max-width: 1120px) {
  .hero, .main-grid, .execution-band, .command-grid {
    grid-template-columns: 1fr;
  }
  .metrics-grid {
    grid-template-columns: repeat(2, minmax(140px, 1fr));
  }
  .monitor {
    position: static;
  }
}
@media (max-width: 760px) {
  .metrics-grid, .summary-grid {
    grid-template-columns: 1fr;
  }
}
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.001ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.001ms !important;
    scroll-behavior: auto !important;
  }
}
"""


def _render_dashboard_js() -> str:
    return """
// TheWorkshop dashboard runtime: auto-refresh, filtering, triage queue, and keyboard shortcuts.
(function () {
  var REFRESH_MS = 5000;
  var STALE_AFTER_MS = Math.max(5 * 60 * 1000, 2 * REFRESH_MS);
  var LS_REFRESH = "theworkshop.autorefresh.enabled";
  var LS_QUERY = "theworkshop.ui.query";
  var LS_STATUS = "theworkshop.ui.status";
  var LS_TRUTH = "theworkshop.ui.truth";
  var LS_FOCUS = "theworkshop.ui.focus";
  var LS_COLLAPSED = "theworkshop.ui.collapsed_ws";
  var SS_SCROLL_KEY = "theworkshop.autorefresh.scrollY";
  var DEFAULT_STATUS = ["planned", "in_progress", "blocked", "done", "cancelled"];
  var DEFAULT_TRUTH = ["pass", "fail", "unknown"];

  function $(id) { return document.getElementById(id); }
  function qsa(selector) { return Array.prototype.slice.call(document.querySelectorAll(selector)); }
  function lsGet(key, fallback) {
    try { return window.localStorage.getItem(key) || fallback; } catch (e) { return fallback; }
  }
  function lsSet(key, value) {
    try { window.localStorage.setItem(key, value); } catch (e) {}
  }
  function lsGetList(key, fallback) {
    var raw = lsGet(key, "");
    if (!raw) return fallback.slice();
    try {
      var parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) return parsed.map(function (v) { return String(v); });
    } catch (e) {}
    return fallback.slice();
  }
  function lsSetList(key, list) {
    try { window.localStorage.setItem(key, JSON.stringify(list)); } catch (e) {}
  }
  function ssGet(key, fallback) {
    try { return window.sessionStorage.getItem(key) || fallback; } catch (e) { return fallback; }
  }
  function ssSet(key, value) {
    try { window.sessionStorage.setItem(key, value); } catch (e) {}
  }
  function setText(el, text) { if (el) el.textContent = text; }
  function show(el, on) { if (el) el.style.display = on ? "" : "none"; }
  function escHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  function parseNum(v) {
    var n = Number(v);
    return isFinite(n) ? n : 0;
  }
  function saveScroll() {
    try { ssSet(SS_SCROLL_KEY, String(window.scrollY || 0)); } catch (e) {}
  }
  function restoreScroll() {
    var y = parseInt(ssGet(SS_SCROLL_KEY, "0"), 10);
    if (!isNaN(y) && y > 0) window.scrollTo(0, y);
  }

  var queryEl = $("twQuery");
  var queueBody = $("twQueueBody");
  var queueTable = $("twQueueTable");
  var eventRows = qsa("[data-event-row]");
  var focusButtons = qsa("[data-focus-btn]");
  var statusChips = qsa("[data-status-chip]");
  var truthChips = qsa("[data-truth-chip]");
  var collapseAllBtn = $("twCollapseAll");
  var expandAllBtn = $("twExpandAll");
  var visibleJobsEl = $("twVisibleJobs");
  var atRiskJobsEl = $("twAtRiskJobs");
  var activeJobsEl = $("twActiveJobs");

  var rowModels = qsa("[data-wi-row]").map(function (row) {
    var rewardScore = parseNum(row.getAttribute("data-reward-score"));
    var rewardTarget = parseNum(row.getAttribute("data-reward-target"));
    var rewardGap = Math.max(0, rewardTarget - rewardScore);
    var model = {
      row: row,
      anchor: String(row.id || ""),
      wiId: String(row.getAttribute("data-wi-id") || ""),
      title: String(row.getAttribute("data-title") || ""),
      wsId: String(row.getAttribute("data-ws-id") || ""),
      wsTitle: String(row.getAttribute("data-ws-title") || ""),
      status: String(row.getAttribute("data-status") || "planned"),
      truth: String(row.getAttribute("data-truth") || "unknown"),
      nextAction: String(row.getAttribute("data-next-action") || ""),
      loopStatus: String(row.getAttribute("data-loop-status") || ""),
      rewardScore: rewardScore,
      rewardTarget: rewardTarget,
      rewardGap: rewardGap
    };
    model.search = (model.wiId + " " + model.title + " " + model.nextAction + " " + model.wsId + " " + model.wsTitle).toLowerCase();
    return model;
  });

  var wsCards = qsa("[data-ws-card]").map(function (card) {
    return {
      card: card,
      wsId: String(card.getAttribute("data-ws-id") || ""),
      body: card.querySelector("[data-ws-body]"),
      toggle: card.querySelector("[data-ws-toggle]"),
      visibleCount: card.querySelector("[data-visible-count]")
    };
  });
  var wsById = {};
  wsCards.forEach(function (entry) { wsById[entry.wsId] = entry; });

  var state = {
    query: String(lsGet(LS_QUERY, "") || ""),
    focus: String(lsGet(LS_FOCUS, "all") || "all"),
    status: new Set(lsGetList(LS_STATUS, DEFAULT_STATUS)),
    truth: new Set(lsGetList(LS_TRUTH, DEFAULT_TRUTH)),
    collapsed: new Set(lsGetList(LS_COLLAPSED, []))
  };
  if (!state.status.size) DEFAULT_STATUS.forEach(function (s) { state.status.add(s); });
  if (!state.truth.size) DEFAULT_TRUTH.forEach(function (s) { state.truth.add(s); });

  if (queryEl) queryEl.value = state.query;

  function persistUiState() {
    lsSet(LS_QUERY, state.query);
    lsSet(LS_FOCUS, state.focus);
    lsSetList(LS_STATUS, Array.from(state.status));
    lsSetList(LS_TRUTH, Array.from(state.truth));
    lsSetList(LS_COLLAPSED, Array.from(state.collapsed));
  }

  function renderFocusButtons() {
    focusButtons.forEach(function (btn) {
      var mode = String(btn.getAttribute("data-focus-btn") || "");
      btn.classList.toggle("is-active", mode === state.focus);
    });
  }

  function renderFilterButtons() {
    statusChips.forEach(function (btn) {
      var value = String(btn.getAttribute("data-status-chip") || "");
      btn.classList.toggle("is-on", state.status.has(value));
    });
    truthChips.forEach(function (btn) {
      var value = String(btn.getAttribute("data-truth-chip") || "");
      btn.classList.toggle("is-on", state.truth.has(value));
    });
  }

  function applyWsCollapse() {
    wsCards.forEach(function (entry) {
      var isCollapsed = state.collapsed.has(entry.wsId);
      if (entry.body) entry.body.hidden = isCollapsed;
      if (entry.toggle) entry.toggle.textContent = isCollapsed ? "Expand" : "Collapse";
    });
  }

  function rowRiskScore(meta) {
    var score = 0;
    if (meta.status === "blocked") score += 100;
    if (meta.truth === "fail") score += 80;
    if (meta.status === "in_progress") score += 40;
    score += meta.rewardGap;
    return score;
  }

  function focusMatch(meta) {
    if (state.focus === "all") return true;
    if (state.focus === "at_risk") return meta.status === "blocked" || meta.truth === "fail" || meta.rewardGap > 0;
    if (state.focus === "active") return meta.status === "in_progress";
    if (state.focus === "blocked") return meta.status === "blocked";
    if (state.focus === "done") return meta.status === "done";
    return true;
  }

  function updateChipCount(kind, key, count) {
    var selector = '[data-chip-count="' + kind + ':' + key + '"]';
    var node = document.querySelector(selector);
    if (node) node.textContent = String(count);
  }

  function renderQueue(items) {
    if (!queueBody) return;
    if (!items.length) {
      queueBody.innerHTML = '<tr><td colspan="6" class="muted">(no jobs match current filters)</td></tr>';
      return;
    }
    var sorted = items.slice().sort(function (a, b) {
      var riskDelta = rowRiskScore(b) - rowRiskScore(a);
      if (riskDelta !== 0) return riskDelta;
      return a.wiId.localeCompare(b.wiId);
    });
    var html = sorted.map(function (meta) {
      var statusPill = '<span class="pill st-' + (meta.status === "in_progress" ? "inprogress" : meta.status) + '">' + escHtml(meta.status) + '</span>';
      var truthPill = '<span class="truth-pill truth-' + escHtml(meta.truth) + '">' + escHtml(meta.truth) + '</span>';
      var gap = meta.rewardGap > 0 ? '<span class="flag-risk">+' + meta.rewardGap + '</span>' : '0';
      var risk = rowRiskScore(meta);
      return (
        '<tr data-target-row="' + escHtml(meta.anchor) + '">' +
        '<td><code>' + escHtml(meta.wiId) + '</code></td>' +
        '<td>' + statusPill + '</td>' +
        '<td>' + truthPill + '</td>' +
        '<td>' + gap + '</td>' +
        '<td>' + escHtml(meta.nextAction || "(none)") + '</td>' +
        '<td class="mono">' + escHtml(meta.wsId) + ' · risk ' + risk + '</td>' +
        '</tr>'
      );
    }).join("");
    queueBody.innerHTML = html;
  }

  function applyEventSearch(query) {
    eventRows.forEach(function (row) {
      var hay = String(row.getAttribute("data-event-search") || "").toLowerCase();
      if (!query || hay.indexOf(query) >= 0) {
        row.style.display = "";
      } else {
        row.style.display = "none";
      }
    });
  }

  function applyFilters() {
    var query = state.query.trim().toLowerCase();
    var statusCounts = { planned: 0, in_progress: 0, blocked: 0, done: 0, cancelled: 0 };
    var truthCounts = { pass: 0, fail: 0, unknown: 0 };
    var wsVisible = {};
    var visible = [];
    var activeCount = 0;
    var riskCount = 0;

    rowModels.forEach(function (meta) {
      if ((query && meta.search.indexOf(query) === -1) || !focusMatch(meta)) {
        meta.row.style.display = "none";
        return;
      }
      if (statusCounts.hasOwnProperty(meta.status)) statusCounts[meta.status] += 1;
      if (truthCounts.hasOwnProperty(meta.truth)) truthCounts[meta.truth] += 1;

      if (!state.status.has(meta.status) || !state.truth.has(meta.truth)) {
        meta.row.style.display = "none";
        return;
      }
      meta.row.style.display = "";
      if (meta.status === "in_progress") activeCount += 1;
      if (meta.status === "blocked" || meta.truth === "fail" || meta.rewardGap > 0) riskCount += 1;
      meta.row.classList.toggle("is-risk", meta.status === "blocked" || meta.truth === "fail" || meta.rewardGap > 0);
      wsVisible[meta.wsId] = (wsVisible[meta.wsId] || 0) + 1;
      visible.push(meta);
    });

    wsCards.forEach(function (entry) {
      var count = wsVisible[entry.wsId] || 0;
      if (entry.visibleCount) entry.visibleCount.textContent = String(count);
      entry.card.style.display = count > 0 ? "" : "none";
    });

    DEFAULT_STATUS.forEach(function (s) { updateChipCount("status", s, statusCounts[s] || 0); });
    DEFAULT_TRUTH.forEach(function (t) { updateChipCount("truth", t, truthCounts[t] || 0); });
    if (visibleJobsEl) visibleJobsEl.textContent = String(visible.length);
    if (activeJobsEl) activeJobsEl.textContent = String(activeCount);
    if (atRiskJobsEl) atRiskJobsEl.textContent = String(riskCount);

    applyEventSearch(query);
    renderQueue(visible);
    renderFilterButtons();
    renderFocusButtons();
  }

  function setFocus(mode) {
    state.focus = mode;
    persistUiState();
    applyFilters();
  }

  focusButtons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      setFocus(String(btn.getAttribute("data-focus-btn") || "all"));
    });
  });

  statusChips.forEach(function (btn) {
    btn.addEventListener("click", function () {
      var key = String(btn.getAttribute("data-status-chip") || "");
      if (!key) return;
      if (state.status.has(key)) {
        if (state.status.size <= 1) return;
        state.status.delete(key);
      } else {
        state.status.add(key);
      }
      persistUiState();
      applyFilters();
    });
  });

  truthChips.forEach(function (btn) {
    btn.addEventListener("click", function () {
      var key = String(btn.getAttribute("data-truth-chip") || "");
      if (!key) return;
      if (state.truth.has(key)) {
        if (state.truth.size <= 1) return;
        state.truth.delete(key);
      } else {
        state.truth.add(key);
      }
      persistUiState();
      applyFilters();
    });
  });

  if (queryEl) {
    queryEl.addEventListener("input", function () {
      state.query = queryEl.value || "";
      persistUiState();
      applyFilters();
    });
  }

  wsCards.forEach(function (entry) {
    if (!entry.toggle) return;
    entry.toggle.addEventListener("click", function () {
      if (state.collapsed.has(entry.wsId)) state.collapsed.delete(entry.wsId);
      else state.collapsed.add(entry.wsId);
      persistUiState();
      applyWsCollapse();
    });
  });

  if (collapseAllBtn) {
    collapseAllBtn.addEventListener("click", function () {
      wsCards.forEach(function (entry) { state.collapsed.add(entry.wsId); });
      persistUiState();
      applyWsCollapse();
    });
  }

  if (expandAllBtn) {
    expandAllBtn.addEventListener("click", function () {
      state.collapsed.clear();
      persistUiState();
      applyWsCollapse();
    });
  }

  if (queueBody) {
    queueBody.addEventListener("click", function (evt) {
      var tr = evt.target && evt.target.closest ? evt.target.closest("tr[data-target-row]") : null;
      if (!tr) return;
      var targetId = String(tr.getAttribute("data-target-row") || "");
      if (!targetId) return;
      var target = document.getElementById(targetId);
      if (!target) return;
      target.scrollIntoView({ behavior: "smooth", block: "center" });
      target.classList.add("row-focus");
      window.setTimeout(function () { target.classList.remove("row-focus"); }, 1600);
    });
  }

  document.addEventListener("keydown", function (evt) {
    var key = String(evt.key || "");
    var active = document.activeElement;
    var tag = active && active.tagName ? String(active.tagName).toLowerCase() : "";
    var typing = tag === "input" || tag === "textarea" || (active && active.isContentEditable);
    if (key === "/" && !typing) {
      evt.preventDefault();
      if (queryEl) {
        queryEl.focus();
        queryEl.select();
      }
      return;
    }
    if (key === "Escape") {
      state.query = "";
      state.focus = "all";
      state.status = new Set(DEFAULT_STATUS);
      state.truth = new Set(DEFAULT_TRUTH);
      if (queryEl) queryEl.value = "";
      persistUiState();
      applyFilters();
      return;
    }
    if (typing) return;
    var lower = key.toLowerCase();
    if (lower === "a") setFocus("all");
    else if (lower === "r") setFocus("at_risk");
    else if (lower === "i") setFocus("active");
    else if (lower === "b") setFocus("blocked");
    else if (lower === "d") setFocus("done");
  });

  var root = document.documentElement || null;
  var rootProjectStatus = String(root && root.getAttribute("data-project-status") || "").toLowerCase();
  var rootMonitorStatus = String(root && root.getAttribute("data-monitor-status") || "").toLowerCase();
  var persistedEnabled = lsGet(LS_REFRESH, "1") !== "0";
  var refreshState = persistedEnabled ? "ON" : "PAUSED";
  var nextAt = Date.now() + REFRESH_MS;
  var genAtStr = document.documentElement.getAttribute("data-generated-at") || "";
  var genAtMs = Date.parse(genAtStr);
  var lastGeneratedAt = genAtStr;
  var sse = null;
  var sseConnected = false;
  var sseEnabled = (window.location.protocol || "").indexOf("http") === 0;
  var offlineProbeUntil = 0;
  var nextReconnectAt = 0;
  var RECONNECT_STEP_MS = 1000;

  var elToggle = $("twRefreshToggle");
  var elNow = $("twRefreshNow");
  var elCountdown = $("twRefreshCountdown");
  var elStatus = $("twRefreshStatus");
  var elStale = $("twStaleBadge");
  var elAge = $("twDataAge");

  function isTerminalStatus(status) {
    return status === "done" || status === "cancelled" || status === "terminal";
  }

  function disconnectSSE() {
    if (sse) {
      try { sse.close(); } catch (e) {}
    }
    sse = null;
    sseConnected = false;
  }

  function setRefreshState(nextState) {
    refreshState = String(nextState || "ON");
    renderRefresh();
  }

  function freezeTerminal() {
    offlineProbeUntil = 0;
    nextReconnectAt = 0;
    disconnectSSE();
    setRefreshState("FROZEN");
  }

  function goOffline() {
    offlineProbeUntil = 0;
    nextReconnectAt = 0;
    disconnectSSE();
    setRefreshState("OFFLINE");
  }

  function reloadNow() {
    saveScroll();
    var base = window.location.href.split("?")[0];
    window.location.replace(base + "?t=" + Date.now());
  }

  function connectSSE() {
    if (!sseEnabled || typeof window.EventSource === "undefined" || sse) {
      return false;
    }
    try {
      sse = new window.EventSource("/events");
    } catch (e) {
      sse = null;
      return false;
    }
    sse.onopen = function () {
      sseConnected = true;
      offlineProbeUntil = 0;
      nextReconnectAt = 0;
      if (refreshState !== "PAUSED" && refreshState !== "FROZEN") {
        refreshState = "LIVE";
      }
      renderRefresh();
    };
    sse.onerror = function () {
      var probing = offlineProbeUntil > 0;
      disconnectSSE();
      if (refreshState === "PAUSED" || refreshState === "FROZEN") {
        renderRefresh();
        return;
      }
      if (!probing) {
        goOffline();
        return;
      }
      renderRefresh();
    };
    sse.onmessage = function (evt) {
      try {
        var payload = JSON.parse(evt.data || "{}");
        var incoming = String(payload.generated_at || "");
        if (!incoming && isTerminalStatus(String(payload.project_status || "").toLowerCase())) {
          freezeTerminal();
          return;
        }
        if (incoming && incoming !== lastGeneratedAt) {
          lastGeneratedAt = incoming;
          reloadNow();
        }
      } catch (e) {}
    };
    return true;
  }

  function armOfflineProbe() {
    offlineProbeUntil = Date.now() + REFRESH_MS;
    nextReconnectAt = 0;
    disconnectSSE();
    setRefreshState("ON");
  }

  function fmtAge(seconds) {
    var s = Math.max(0, Math.floor(seconds));
    var m = Math.floor(s / 60);
    var r = s % 60;
    if (m <= 0) return s + "s";
    return m + "m " + r + "s";
  }

  function renderRefresh() {
    if (elStatus) {
      var stateLabel = refreshState;
      var className = "badge badge-on";
      if (refreshState === "PAUSED") className = "badge badge-off";
      else if (refreshState === "FROZEN") className = "badge badge-frozen";
      else if (refreshState === "OFFLINE") className = "badge badge-offline";
      elStatus.textContent = stateLabel;
      elStatus.className = className;
    }
    if (elToggle) elToggle.textContent = (refreshState === "ON" || refreshState === "LIVE") ? "Pause" : "Resume";
  }

  function tick() {
    var now = Date.now();
    if (!isNaN(genAtMs)) setText(elAge, fmtAge((now - genAtMs) / 1000));
    if (!isNaN(genAtMs) && (now - genAtMs) > STALE_AFTER_MS) show(elStale, true);
    else show(elStale, false);

    if (refreshState === "PAUSED") {
      setText(elCountdown, "paused");
      return;
    }
    if (refreshState === "FROZEN") {
      setText(elCountdown, "frozen");
      return;
    }
    if (refreshState === "OFFLINE") {
      setText(elCountdown, "feed lost");
      return;
    }
    if (refreshState === "LIVE" && sseEnabled && sseConnected) {
      setText(elCountdown, "live");
      return;
    }
    if (offlineProbeUntil > 0) {
      if (!sseConnected && !sse && now >= nextReconnectAt) {
        nextReconnectAt = now + RECONNECT_STEP_MS;
        connectSSE();
      }
      if (sseConnected) {
        offlineProbeUntil = 0;
        nextReconnectAt = 0;
        setText(elCountdown, "live");
        return;
      }
      if (now >= offlineProbeUntil) {
        goOffline();
        setText(elCountdown, "feed lost");
        return;
      }
      setText(elCountdown, "retry " + Math.ceil((offlineProbeUntil - now) / 1000) + "s");
      return;
    }
    var remaining = Math.max(0, nextAt - now);
    setText(elCountdown, Math.ceil(remaining / 1000) + "s");
    if (now >= nextAt) reloadNow();
  }

  if (elToggle) {
    elToggle.addEventListener("click", function () {
      if (refreshState === "ON" || refreshState === "LIVE") {
        offlineProbeUntil = 0;
        nextReconnectAt = 0;
        disconnectSSE();
        lsSet(LS_REFRESH, "0");
        setRefreshState("PAUSED");
      } else {
        lsSet(LS_REFRESH, "1");
        nextAt = Date.now() + REFRESH_MS;
        if (refreshState === "OFFLINE") armOfflineProbe();
        else {
          offlineProbeUntil = 0;
          nextReconnectAt = 0;
          setRefreshState("ON");
          connectSSE();
        }
      }
      tick();
    });
  }
  if (elNow) {
    elNow.addEventListener("click", function () {
      reloadNow();
    });
  }

  applyWsCollapse();
  applyFilters();
  if (isTerminalStatus(rootProjectStatus) || rootMonitorStatus === "terminal") {
    freezeTerminal();
  } else {
    if (refreshState !== "PAUSED") {
      connectSSE();
    }
    renderRefresh();
  }
  tick();
  restoreScroll();
  window.addEventListener("beforeunload", function () {
    saveScroll();
    disconnectSSE();
  });
  window.setInterval(tick, 250);
})();
"""


def _render_dashboard_layout(content: dict[str, str]) -> str:
    return f"""
<div class="wrap">
  <div id="twMonitor" class="monitor">
    <div class="group">
      <span class="muted"><b>Auto-refresh</b></span>
      <span id="twRefreshStatus" class="badge badge-on">ON</span>
      <span class="muted">next in <b id="twRefreshCountdown">5s</b></span>
      <button id="twRefreshToggle" type="button">Pause</button>
      <button id="twRefreshNow" type="button">Refresh now</button>
    </div>
    <div class="group">
      <span id="twStaleBadge" class="badge badge-stale" style="display:none;">STALE</span>
      <span class="muted">data age <b id="twDataAge">0s</b></span>
      <span class="muted">generated <code id="twGeneratedAt">{content["generated_at"]}</code></span>
    </div>
  </div>

  <section class="hero">
    <div>
      <div class="hero-title-row">
        <h1>TheWorkshop Dashboard</h1>
        <span class="pill {content["project_status_class"]}">{content["project_status"]}</span>
      </div>
      <div class="project-line muted">
        <b>{content["project_id"]}</b>
        <span>{content["project_title"]}</span>
        <span>generated {content["generated_at"]}</span>
      </div>
      <p class="hero-copy">{content["project_health_line"]}</p>
    </div>
    <div class="hero-meta">
      <div class="summary-grid">
        <div class="summary-card">
          <div class="summary-kicker">Agreement</div>
          <div class="summary-stat"><b>{content["agreement_status"]}</b></div>
          <div class="summary-detail">project elapsed {content["project_elapsed"]}</div>
        </div>
        <div class="summary-card">
          <div class="summary-kicker">Runtime</div>
          <div class="summary-stat"><b>{content["monitor_status"]}</b></div>
          <div class="summary-detail">{content["runtime_summary_line"]}</div>
        </div>
      </div>
    </div>
  </section>

  <section class="card command-bar">
    <div class="command-grid">
      <div class="query-wrap">
        <span class="mono">query:</span>
        <input id="twQuery" type="text" placeholder="Filter by WI, title, next action, workstream" aria-label="Filter jobs">
        <span class="hint">/</span>
      </div>
      <div class="focus-group">
        <button id="twFocusAll" class="focus-btn is-active" data-focus-btn="all" type="button">All <span class="kbd">A</span></button>
        <button id="twFocusAtRisk" class="focus-btn" data-focus-btn="at_risk" type="button">At Risk <span class="kbd">R</span></button>
        <button id="twFocusActive" class="focus-btn" data-focus-btn="active" type="button">Active <span class="kbd">I</span></button>
        <button id="twFocusBlocked" class="focus-btn" data-focus-btn="blocked" type="button">Blocked <span class="kbd">B</span></button>
        <button id="twFocusDone" class="focus-btn" data-focus-btn="done" type="button">Done <span class="kbd">D</span></button>
      </div>
      <div class="muted mono">Esc resets filters</div>
    </div>
    <div class="command-grid" style="margin-top:10px;">
      <div class="filter-group" id="twStatusFilters" aria-label="Status filters">
        <span class="muted"><b>Status</b></span>
        {content["status_filters_html"]}
      </div>
      <div class="filter-group" id="twTruthFilters" aria-label="Truth filters">
        <span class="muted"><b>Truth</b></span>
        {content["truth_filters_html"]}
      </div>
      <div class="muted">
        visible jobs <b id="twVisibleJobs">{content["jobs_total"]}</b> · active <b id="twActiveJobs">{content["jobs_in_progress"]}</b> · at risk <b id="twAtRiskJobs">{content["jobs_at_risk"]}</b>
      </div>
    </div>
  </section>

  <section class="execution-band">
    <section class="card execution-card" data-primary-panel="now">
      <div>
        <h3>Now Working</h3>
        <p class="muted">Active jobs and current execution pressure.</p>
      </div>
      <div class="value">{content["jobs_in_progress"]}</div>
      <div class="muted">loop jobs active {content["loops_active"]} · watcher {content["monitor_watch_state"]}</div>
      {content["active_jobs_html"]}
    </section>
    <section class="card execution-card" data-primary-panel="risk">
      <div>
        <h3>Needs Attention</h3>
        <p class="muted">Top risk item by blocked/truth/reward heuristics.</p>
      </div>
      <div class="value risk">{content["jobs_at_risk"]}</div>
      <div class="muted">{content["attention_summary"]}</div>
      {content["attention_jobs_html"]}
    </section>
    <section class="card execution-card" data-primary-panel="next">
      <div>
        <h3>Next Action</h3>
        <p class="muted">The clearest next move available from current reward and truth state.</p>
      </div>
      <div class="value">{content["next_action_title"]}</div>
      <div class="muted">{content["next_action_summary"]}</div>
      {content["next_action_html"]}
    </section>
  </section>

  <section class="metrics-grid">
    <section class="card metric"><h3>Workstreams</h3><div class="value">{content["workstreams_total"]}</div><div class="split">waves {content["waves_count"]}</div></section>
    <section class="card metric"><h3>Jobs</h3><div class="value">{content["jobs_total"]}</div><div class="split">done {content["jobs_done"]} · cancelled {content["jobs_cancelled"]}</div></section>
    <section class="card metric"><h3>Truth</h3><div class="value">{content["truth_fail"]}</div><div class="split">fail · pass {content["truth_pass"]} · unknown {content["truth_unknown"]}</div></section>
    <section class="card metric"><h3>Execution</h3><div class="value">{content["commands"]}</div><div class="split">failures {content["failures"]} · avg {content["avg_duration_sec"]}s</div></section>
  </section>

  <div class="main-grid">
    <div class="primary-stack">
      <section class="card">
        <div class="triage-head">
          <div>
            <h3>Triage Queue</h3>
            <p class="legend">Sorted by deterministic risk: blocked +100, truth fail +80, in_progress +40, reward gap +gap</p>
          </div>
        </div>
        <div class="queue-wrap">
          <table id="twQueueTable">
            <thead><tr><th>Work Item</th><th>Status</th><th>Truth</th><th>Reward Gap</th><th>Next Action</th><th>Workstream / Risk</th></tr></thead>
            <tbody id="twQueueBody"><tr><td colspan="6" class="muted">(initializing)</td></tr></tbody>
          </table>
        </div>
      </section>

      {content["waves_block"]}

      <section class="card" data-primary-panel="workstreams">
        <div class="ws-controls">
          <h3>Workstream Explorer</h3>
          <div>
            <button id="twCollapseAll" type="button">Collapse all</button>
            <button id="twExpandAll" type="button">Expand all</button>
          </div>
        </div>
        {content["ws_cards_html"]}
      </section>
    </div>

    <div class="secondary-stack">
      <section class="card" data-secondary-panel="runtime">
        <h3>Runtime & Health</h3>
        <div class="diagnostic-list">
          <div class="diagnostic-row"><span>Monitor</span><b>{content["monitor_status"]}</b></div>
          <div class="diagnostic-row"><span>Policy</span><b>{content["monitor_policy"]}</b></div>
          <div class="diagnostic-row"><span>Watcher</span><b>{content["monitor_watch_state"]} · pid {content["monitor_watch_pid"]}</b></div>
          <div class="diagnostic-row"><span>Server</span><b>{content["monitor_server_state"]} · pid {content["monitor_server_pid"]}</b></div>
          <div class="diagnostic-row"><span>Cleanup</span><b>{content["monitor_cleanup_status"]}</b></div>
          <div class="diagnostic-row"><span>Projection seq</span><b>{content["projection_seq"]}</b></div>
        </div>
        <p class="muted">{content["monitor_server_url"]}</p>
        <p class="muted">warnings: {content["projection_warning_count"]}</p>
        <ul class="monitor-list">{content["monitor_warning_lines"]}</ul>
      </section>

      <section class="card" data-secondary-panel="activity">
        <div id="twLiveStrip" class="live-strip">
          <span class="live-label">Recent Activity</span>
          <div class="live-scroll">
            <div class="live-track{content["ticker_track_class"]}" style="--ticker-duration:{content["ticker_duration"]}s;">{content["ticker_items_html"]}</div>
          </div>
        </div>
      </section>

      <section class="card" data-secondary-panel="orchestration">
        <h3>Orchestration</h3>
        <p class="muted">source: {content["orchestration_path"]}</p>
        <p><b>Parallel Groups</b></p>
        {content["groups_block"]}
        <p><b>Critical Path</b></p>
        {content["critical_path_block"]}
      </section>

      <section class="card" data-secondary-panel="subagents">
        <h3>Sub-Agents</h3>
        <p>{content["subagents_line"]}</p>
        <p class="muted">source: {content["subagents_path"]}</p>
        <p class="muted">{content["subagents_note"]}</p>
        <div class="event-list-wrap">
          {content["recent_events_block"]}
        </div>
      </section>

      <section class="card" data-secondary-panel="dispatch">
        <h3>Dispatch Engine</h3>
        <p>{content["dispatch_line"]}</p>
        <p class="muted">{content["dispatch_note"]}</p>
        <p class="muted">source: {content["dispatch_path"]}</p>
        <p class="muted">execution: {content["dispatch_execution_path"]}</p>
        {content["dispatch_summary_block"]}
      </section>

      <section class="card" data-secondary-panel="spend">
        <h3>{content["spend_table_title"]}</h3>
        <p class="muted">{content["rate_resolution"]}</p>
        <p class="muted">{content["billing_reason"]}</p>
        <table>
          <thead><tr><th>Task</th><th>Estimated Cost</th><th>Weight</th><th>Tokens Allocated</th></tr></thead>
          <tbody>{content["wi_spend_rows_html"]}</tbody>
        </table>
      </section>

      <section class="card" data-secondary-panel="paths">
        <h3>Paths</h3>
        <ul>
          <li><code>outputs/dashboard.json</code></li>
          <li><code>outputs/dashboard.md</code></li>
          <li><code>outputs/dashboard.html</code></li>
        </ul>
        <p class="muted">token source {content["token_source_label"]} · billed session {content["billed_session_cost_label"]}</p>
      </section>
    </div>
  </div>
</div>
"""


def render_html(payload: dict) -> str:
    proj = payload["project"]
    stats = payload["stats"]
    logs = payload["execution_logs"]
    toks = payload["tokens"]
    gh = payload["github_sync"]
    ws = payload["workstreams"]
    truth = payload.get("truth_summary") or {}
    orchestration = payload.get("orchestration") or {}
    subagents = payload.get("subagents") or {}
    dispatch = payload.get("dispatch") or {}
    projection_seq = int(payload.get("projection_seq") or 0)
    projection_warnings = payload.get("projection_warnings") if isinstance(payload.get("projection_warnings"), list) else []
    monitor_state = payload.get("monitor_state") if isinstance(payload.get("monitor_state"), dict) else {}
    monitor_status = str(monitor_state.get("status") or "unknown")
    monitor_policy = str(monitor_state.get("policy") or "always")
    monitor_watch_alive = bool(monitor_state.get("watch_alive"))
    monitor_watch_pid = int(monitor_state.get("watch_pid") or 0)
    monitor_server_alive = bool(monitor_state.get("server_alive"))
    monitor_server_pid = int(monitor_state.get("server_pid") or 0)
    monitor_server_url = str(monitor_state.get("server_url") or "")
    monitor_cleanup_status = str(monitor_state.get("cleanup_status") or "none")
    sub_counts = (subagents.get("counts") or {}) if isinstance(subagents, dict) else {}
    dispatch_counts = (dispatch.get("counts") or {}) if isinstance(dispatch, dict) else {}

    def fmt_usd(value: Any) -> str:
        try:
            amount = float(value)
        except Exception:
            return "n/a"
        return f"${amount:,.4f}"

    generated_at = html_escape(payload["generated_at"])
    token_source = str(toks.get("token_source") or "none")
    billing_mode = str(toks.get("billing_mode") or "unknown")
    token_source_label = (
        "codexbar"
        if token_source == "codexbar"
        else "codex auth session logs"
        if token_source == "codex_session_logs" and billing_mode == "subscription_auth"
        else "codex session logs"
        if token_source == "codex_session_logs"
        else "not available"
    )
    cost_source = str(toks.get("cost_source") or "none")
    cost_source_label = (
        "codexbar exact"
        if cost_source == "codexbar_exact"
        else "estimated from rates"
        if cost_source == "estimated_from_rates"
        else "not available"
    )
    cost_confidence = str(toks.get("cost_confidence") or "none")
    billed_session_cost_label = fmt_usd(toks.get("billed_session_cost_usd"))
    billed_project_cost_label = fmt_usd(toks.get("billed_project_cost_usd"))
    api_equivalent_session_cost_label = fmt_usd(toks.get("api_equivalent_session_cost_usd"))
    api_equivalent_project_cost_label = fmt_usd(toks.get("api_equivalent_project_cost_usd"))
    billing_reason = html_escape(str(toks.get("billing_reason") or ""))
    billing_confidence = html_escape(str(toks.get("billing_confidence") or "low"))
    rate_model_key = html_escape(str(toks.get("rate_model_key") or "n/a"))
    rate_resolution = html_escape(str(toks.get("rate_resolution") or "rate resolution unavailable"))

    truth_pass = int(truth.get("pass") or 0)
    truth_fail = int(truth.get("fail") or 0)
    truth_unknown = int(truth.get("unknown") or 0)
    stale_dependencies = int(truth.get("stale_dependency_count") or 0)
    sub_active = int(sub_counts.get("active") or 0)
    sub_completed = int(sub_counts.get("completed") or 0)
    sub_failed = int(sub_counts.get("failed") or 0)
    dispatch_active = int(dispatch_counts.get("active") or 0)
    dispatch_completed = int(dispatch_counts.get("completed") or 0)
    dispatch_failed = int(dispatch_counts.get("failed") or 0)
    dispatch_blocked = int(dispatch_counts.get("blocked") or 0)
    dispatch_mode = str(dispatch.get("mode") or "not_used")
    dispatch_note = str(dispatch.get("telemetry_note") or "").strip()
    if dispatch_mode == "not_used":
        dispatch_line = "not used in this run"
    else:
        dispatch_line = (
            f"active {dispatch_active} | completed {dispatch_completed} | "
            f"failed {dispatch_failed} | blocked {dispatch_blocked}"
        )

    monitor_warning_lines = (
        "".join(f"<li>{html_escape(str(item))}</li>" for item in projection_warnings)
        if projection_warnings
        else "<li class='muted'>(none)</li>"
    )

    status_filter_keys = ["planned", "in_progress", "blocked", "done", "cancelled"]
    status_filters_html = "".join(
        "<button type='button' class='chip is-on' data-status-chip='{key}'>"
        "{label} <span class='chip-count' data-chip-count='status:{key}'>{count}</span></button>".format(
            key=html_escape(key),
            label=html_escape(key),
            count=int(stats["jobs_status"].get(key) or 0),
        )
        for key in status_filter_keys
    )
    truth_filters_html = "".join(
        "<button type='button' class='chip is-on' data-truth-chip='{key}'>"
        "{label} <span class='chip-count' data-chip-count='truth:{key}'>{count}</span></button>".format(
            key=html_escape(key),
            label=html_escape(key),
            count=truth_pass if key == "pass" else truth_fail if key == "fail" else truth_unknown,
        )
        for key in ["pass", "fail", "unknown"]
    )

    ws_cards: list[str] = []
    job_records: list[dict[str, Any]] = []
    for w in ws:
        ws_id = str(w.get("id") or "")
        ws_title = str(w.get("title") or "")
        ws_status = str(w.get("status") or "planned")
        ws_depends = str(", ".join(w.get("depends_on") or [])) or "(none)"
        rows: list[str] = []
        for j in w["jobs"]:
            wi_id = str(j.get("work_item_id") or "")
            wi_title = str(j.get("title") or "")
            status = str(j.get("status") or "planned")
            truth_status = str(j.get("truth_status") or "unknown")
            truth_snippet = str(j.get("truth_last_failure_snippet") or "")
            loop_status = str(j.get("loop_status") or "idle")
            loop_mode = str(j.get("loop_mode") or "max_iterations")
            loop_target = str(j.get("loop_target_promise") or "")
            loop_target_display = f"target={html_escape(loop_target)}" if loop_target else "target=<none>"
            loop_enabled = "enabled" if bool(j.get("loop_enabled")) else "disabled"
            loop_max = int(j.get("loop_max_iterations") or 0)
            loop_attempts = int(j.get("loop_last_attempt") or 0)
            loop_stop_reason = str(j.get("loop_stop_reason") or "n/a")
            reward_score = int(j.get("reward_score") or 0)
            reward_target = int(j.get("reward_target") or 0)
            reward_gap = max(0, reward_target - reward_score)
            reward_next_action = str(j.get("reward_next_action") or "")
            risk_score = 0
            if status == "blocked":
                risk_score += 100
            if truth_status == "fail":
                risk_score += 80
            if status == "in_progress":
                risk_score += 40
            risk_score += reward_gap
            row_anchor = "twRow-" + re.sub(r"[^A-Za-z0-9_-]", "-", wi_id)
            truth_text = f"<span class='truth-pill {truth_class(truth_status)}'>{html_escape(truth_status)}</span>"
            if truth_snippet:
                truth_text += f"<div class='muted'>{html_escape(truth_snippet)}</div>"

            job_records.append(
                {
                    "wi_id": wi_id,
                    "title": wi_title,
                    "status": status,
                    "truth_status": truth_status,
                    "truth_snippet": truth_snippet,
                    "ws_id": ws_id,
                    "ws_title": ws_title,
                    "reward_gap": reward_gap,
                    "next_action": reward_next_action,
                    "risk_score": risk_score,
                }
            )

            flags: list[str] = []
            if status == "blocked":
                flags.append("<span class='ws-flag risk'>blocked</span>")
            if truth_status == "fail":
                flags.append("<span class='ws-flag risk'>truth fail</span>")
            if reward_gap > 0:
                flags.append(f"<span class='ws-flag risk'>gap +{reward_gap}</span>")
            if loop_status == "active":
                flags.append("<span class='ws-flag'>loop active</span>")
            flags_html = "".join(flags) if flags else "<span class='ws-flag'>stable</span>"

            rows.append(
                "<tr id='{row_anchor}' data-wi-row='1' "
                "data-wi-id='{wi_id}' data-title='{title}' data-ws-id='{ws_id}' data-ws-title='{ws_title}' "
                "data-status='{status}' data-truth='{truth}' data-reward-score='{reward_score}' "
                "data-reward-target='{reward_target}' data-next-action='{next_action}' data-loop-status='{loop_status}'>"
                "<td><code>{wi_id_h}</code></td>"
                "<td>{title_h}</td>"
                "<td><span class='pill {status_class}'>{status_h}</span></td>"
                "<td>{wave}</td>"
                "<td>{depends}</td>"
                "<td>{truth_text}</td>"
                "<td>{flags_html}</td>"
                "<td>{loop_enabled} / <span class='pill {loop_class}'>{loop_status_h}</span></td>"
                "<td>{loop_mode_h} / max {loop_max} / tries {loop_attempts}</td>"
                "<td>{loop_target_display}</td>"
                "<td>{loop_stop_reason_h}</td>"
                "<td>{reward_score}/{reward_target}</td>"
                "<td>{next_action_h}</td>"
                "</tr>".format(
                    row_anchor=html_escape(row_anchor),
                    wi_id=html_escape(wi_id),
                    title=html_escape(wi_title),
                    ws_id=html_escape(ws_id),
                    ws_title=html_escape(ws_title),
                    status=html_escape(status),
                    truth=html_escape(truth_status),
                    reward_score=reward_score,
                    reward_target=reward_target,
                    next_action=html_escape(reward_next_action),
                    loop_status=html_escape(loop_status),
                    wi_id_h=html_escape(wi_id),
                    title_h=html_escape(wi_title),
                    status_class=status_class(status),
                    status_h=html_escape(status),
                    wave=html_escape(str(j.get("wave_id") or "")),
                    depends=html_escape(", ".join(j.get("depends_on") or [])),
                    truth_text=truth_text,
                    flags_html=flags_html,
                    loop_enabled=html_escape(loop_enabled),
                    loop_class=loop_status_class(loop_status),
                    loop_status_h=html_escape(loop_status),
                    loop_mode_h=html_escape(loop_mode),
                    loop_max=loop_max,
                    loop_attempts=loop_attempts,
                    loop_target_display=loop_target_display,
                    loop_stop_reason_h=html_escape(loop_stop_reason),
                    next_action_h=html_escape(reward_next_action),
                )
            )
        rows_html = "".join(rows) if rows else "<tr><td colspan='12' class='muted'>(no jobs)</td></tr>"
        ws_cards.append(
            "<section class='card' data-ws-card='1' data-ws-id='{ws_id}'>"
            "<div class='ws-head'>"
            "<div>"
            "<h3>{ws_id_h}: {ws_title_h} <span class='pill {ws_status_class}'>{ws_status_h}</span></h3>"
            "<p class='ws-summary'>Depends on: {ws_depends_h}</p>"
            "</div>"
            "<div class='meta'>"
            "<span class='muted'>visible <b data-visible-count>{job_count}</b>/{job_count}</span>"
            "<button class='ws-toggle' data-ws-toggle='1' type='button'>Collapse</button>"
            "</div>"
            "</div>"
            "<div class='ws-body' data-ws-body='1'>"
            "<table>"
            "<thead><tr><th>WI</th><th>Title</th><th>Status</th><th>Wave</th><th>Depends On</th><th>Truth</th><th>Flags</th>"
            "<th>Loop</th><th>Loop Config</th><th>Loop Target</th><th>Loop Stop</th><th>Reward</th><th>Next Action</th></tr></thead>"
            "<tbody>{rows_html}</tbody></table>"
            "</div>"
            "</section>".format(
                ws_id=html_escape(ws_id),
                ws_id_h=html_escape(ws_id),
                ws_title_h=html_escape(ws_title),
                ws_status_class=status_class(ws_status),
                ws_status_h=html_escape(ws_status),
                ws_depends_h=html_escape(ws_depends),
                job_count=len(rows),
                rows_html=rows_html,
            )
        )

    risk_records = sorted(job_records, key=lambda item: (-int(item["risk_score"]), str(item["wi_id"])))
    active_records = [item for item in job_records if str(item.get("status") or "") == "in_progress"]
    attention_records = [item for item in risk_records if int(item.get("risk_score") or 0) > 0]
    next_action_record = next((item for item in risk_records if str(item.get("next_action") or "").strip()), None)

    def render_focus_list(items: list[dict[str, Any]], *, empty_text: str, limit: int = 3) -> str:
        picked = items[:limit]
        if not picked:
            return f"<p class='muted'>{html_escape(empty_text)}</p>"
        rows: list[str] = []
        for item in picked:
            next_action = str(item.get("next_action") or "").strip()
            detail = f"{item['ws_id']} · {item['status']} · truth {item['truth_status']}"
            if next_action:
                detail += f" · next {next_action}"
            rows.append(
                "<li>"
                "<div class='line-1'>"
                f"<code>{html_escape(str(item['wi_id']))}</code>"
                f"<span>{html_escape(str(item['title']))}</span>"
                f"<span class='pill {status_class(str(item['status']))}'>{html_escape(str(item['status']))}</span>"
                "</div>"
                f"<div class='line-2'>{html_escape(detail)}</div>"
                "</li>"
            )
        return "<ul class='focus-list'>" + "".join(rows) + "</ul>"

    attention_summary = (
        f"Top risk {attention_records[0]['wi_id']} in {attention_records[0]['ws_id']} "
        f"(risk {int(attention_records[0]['risk_score'])})"
        if attention_records
        else "No blocked, truth-fail, or reward-gap items right now."
    )
    next_action_title = "Ready"
    next_action_summary = "No reward follow-up action is currently queued."
    next_action_html = "<p class='muted'>Reward and truth gates are clear enough that there is no single forced next action.</p>"
    if next_action_record:
        next_action_title = str(next_action_record["wi_id"])
        next_action_summary = f"{next_action_record['ws_id']} · {next_action_record['title']}"
        next_action_html = (
            "<ul class='focus-list'><li>"
            f"<div class='line-1'><code>{html_escape(str(next_action_record['wi_id']))}</code>"
            f"<span>{html_escape(str(next_action_record['title']))}</span></div>"
            f"<div class='line-2'>{html_escape(str(next_action_record['next_action']))}</div>"
            "</li></ul>"
        )

    waves_block = ""
    waves = proj.get("waves", []) or []
    if waves:
        items = []
        for w in waves:
            if isinstance(w, dict):
                wid = w.get("id", "")
                title = w.get("title", "")
                start = w.get("start", "")
                end = w.get("end", "")
                items.append(f"<li><b>{html_escape(wid)}</b> {html_escape(title)} ({html_escape(start)} -> {html_escape(end)})</li>")
            else:
                items.append(f"<li>{html_escape(str(w))}</li>")
        waves_block = "<section class='card'><h3>Waves</h3><ul>" + "".join(items) + "</ul></section>"

    group_rows: list[str] = []
    for idx, group in enumerate(orchestration.get("parallel_groups", []) or []):
        members = [str(m).strip() for m in group if str(m).strip()]
        if not members:
            continue
        group_rows.append(f"<li>Group {idx + 1}: {html_escape(', '.join(members))}</li>")
    groups_block = "<ul>" + "".join(group_rows) + "</ul>" if group_rows else "<p class='muted'>(none)</p>"

    critical_members = [str(m).strip() for m in (orchestration.get("critical_path") or []) if str(m).strip()]
    critical_hours = float(orchestration.get("critical_path_hours") or 0.0)
    if critical_members:
        critical_path_block = (
            f"<p><b>{html_escape(' -> '.join(critical_members))}</b></p>"
            f"<p class='muted'>hours: {critical_hours:.2f}</p>"
        )
    else:
        critical_path_block = "<p class='muted'>(none)</p>"

    recent_event_rows: list[str] = []
    ticker_pairs: list[tuple[str, str]] = []
    for evt in subagents.get("recent_events", []) or []:
        ts = str(evt.get("timestamp") or "").strip()
        display_text = str(evt.get("display_text") or "").strip() or "Agent event"
        display_actor = str(evt.get("display_actor") or "").strip()
        display_work_item = str(evt.get("display_work_item") or "").strip()
        source = str(evt.get("source") or "agent").strip()
        severity = str(evt.get("display_severity") or "info").strip().lower()
        if severity not in {"info", "warn", "error"}:
            severity = "info"
        summary_text = f"{ts} - {display_text}" if ts else display_text
        search_text = " ".join(
            [
                display_text,
                display_actor,
                display_work_item,
                str(evt.get("work_item_id") or ""),
                str(evt.get("source") or ""),
            ]
        ).strip()
        raw_payload = evt.get("raw") if isinstance(evt.get("raw"), dict) else {}
        raw_json = json.dumps(raw_payload, indent=2, sort_keys=True)
        recent_event_rows.append(
            "<li data-event-row='1' data-event-search='{search}'>"
            "<div data-event-summary='1'>"
            "<span class='event-pill {sev}'>{sev_up}</span>"
            "<span>{summary}</span>"
            "</div>"
            "<details data-event-details='1'>"
            "<summary>Raw event details</summary>"
            "<pre class='mono' data-event-raw='1'>{raw}</pre>"
            "</details>"
            "</li>".format(
                search=html_escape(search_text),
                sev=html_escape(severity),
                sev_up=html_escape(severity.upper()),
                summary=html_escape(summary_text),
                raw=html_escape(raw_json),
            )
        )
        ticker_line = str(evt.get("ticker_text") or "").strip() or display_text
        ticker_pairs.append((source, ticker_line))
    recent_events_block = (
        "<ul class='event-list'>" + "".join(recent_event_rows) + "</ul>"
        if recent_event_rows
        else "<p class='muted'>(no events)</p>"
    )

    dispatch_summary_text = str(dispatch.get("display_summary") or "").strip()
    dispatch_summary_block = ""
    if dispatch_summary_text:
        dispatch_summary_block = f"<p class='muted' data-event-summary='1'>{html_escape(dispatch_summary_text)}</p>"
        ticker_pairs.append(("dispatch", dispatch_summary_text))

    deduped_ticker_pairs: list[tuple[str, str]] = []
    seen_ticker_keys: set[str] = set()
    for source, line in ticker_pairs:
        src = str(source or "").strip() or "agent"
        txt = re.sub(r"\s+", " ", str(line or "").strip())
        if not txt:
            continue
        key = f"{src.lower()}|{txt.lower()}"
        if key in seen_ticker_keys:
            continue
        seen_ticker_keys.add(key)
        deduped_ticker_pairs.append((src, txt))

    if not deduped_ticker_pairs:
        note = str(subagents.get("telemetry_note") or "").strip()
        fallback_text = note if note else "No active sub-agent events yet."
        deduped_ticker_pairs = [("system", fallback_text)]

    ticker_items_html = "".join(
        "<span class='live-item'><span class='src'>{src}</span>{line}</span>".format(
            src=html_escape(source),
            line=html_escape(line),
        )
        for source, line in deduped_ticker_pairs[:14]
    )
    ticker_track_class = " is-static" if len(deduped_ticker_pairs) <= 2 else ""
    ticker_duration = str(max(26, min(84, 9 * len(deduped_ticker_pairs))))

    wi_spend_items = toks.get("by_work_item") if isinstance(toks.get("by_work_item"), list) else []
    wi_spend_rows: list[str] = []
    for row in wi_spend_items:
        if not isinstance(row, dict):
            continue
        wi_id = str(row.get("work_item_id") or "")
        wi_display = str(row.get("display_work_item") or "").strip() or wi_id or "Unlinked task"
        wi_cost = fmt_usd(row.get("estimated_cost_usd"))
        wi_weight = str(row.get("weight_basis") or "")
        wi_tokens = str(row.get("tokens_allocated") or 0)
        wi_spend_rows.append(
            "<tr>"
            f"<td>{html_escape(wi_display)}</td>"
            f"<td>{html_escape(wi_cost)}</td>"
            f"<td>{html_escape(wi_weight)}</td>"
            f"<td>{html_escape(wi_tokens)}</td>"
            "</tr>"
        )
    unattributed_cost = fmt_usd(toks.get("unattributed_cost_usd"))
    spend_table_title = (
        "API-Equivalent Spend By Work Item (Estimated)"
        if billing_mode == "subscription_auth"
        else "Spend By Work Item (Estimated)"
    )
    if wi_spend_rows:
        wi_spend_rows.append(
            "<tr>"
            "<td><b>(unattributed)</b></td>"
            f"<td>{html_escape(unattributed_cost)}</td>"
            "<td>-</td>"
            f"<td>{html_escape(str((toks.get('unattributed_tokens_allocated') or 0)))}</td>"
            "</tr>"
        )
    else:
        wi_spend_rows = [
            "<tr><td colspan='4' class='muted'>(no attributable execution logs yet)</td></tr>"
        ]

    jobs_at_risk = len(attention_records)
    billing_plan_label = (
        "Codex auth/subscription"
        if billing_mode == "subscription_auth"
        else "metered API"
        if billing_mode == "metered_api"
        else "unknown"
    )
    project_health_line = (
        f"{len(active_records)} active · {jobs_at_risk} at risk · "
        f"{int(stats['jobs_status'].get('done') or 0)} complete · "
        f"dispatch {dispatch_line.lower()}"
    )
    runtime_summary_line = (
        f"watcher {('alive' if monitor_watch_alive else 'stopped')} · "
        f"server {('alive' if monitor_server_alive else 'stopped')} · cleanup {monitor_cleanup_status}"
    )

    content: dict[str, str] = {
        "generated_at": generated_at,
        "project_id": html_escape(str(proj.get("id") or "")),
        "project_title": html_escape(str(proj.get("title") or "")),
        "project_status": html_escape(str(proj.get("status") or "")),
        "project_status_class": status_class(str(proj.get("status") or "")),
        "agreement_status": html_escape(str(proj.get("agreement_status") or "")),
        "project_elapsed": html_escape(str(proj.get("elapsed") or "n/a")),
        "project_health_line": html_escape(project_health_line),
        "runtime_summary_line": html_escape(runtime_summary_line),
        "status_filters_html": status_filters_html,
        "truth_filters_html": truth_filters_html,
        "workstreams_total": str(stats["workstreams_total"]),
        "waves_count": str(len(waves)),
        "jobs_total": str(stats["jobs_total"]),
        "jobs_done": str(stats["jobs_status"]["done"]),
        "jobs_cancelled": str(stats["jobs_status"]["cancelled"]),
        "jobs_in_progress": str(stats["jobs_status"]["in_progress"]),
        "jobs_blocked": str(stats["jobs_status"]["blocked"]),
        "jobs_planned": str(stats["jobs_status"]["planned"]),
        "truth_pass": str(truth_pass),
        "truth_fail": str(truth_fail),
        "truth_unknown": str(truth_unknown),
        "stale_dependencies": str(stale_dependencies),
        "commands": str(logs["commands"]),
        "failures": str(logs["failures"]),
        "avg_duration_sec": f"{logs['avg_duration_sec']:.2f}",
        "subagents_line": html_escape(f"active {sub_active} | completed {sub_completed} | failed {sub_failed}"),
        "dispatch_line": html_escape(dispatch_line),
        "loops_enabled": str(stats["loops_enabled"]),
        "loops_active": str(stats["loops_active"]),
        "loops_blocked": str(stats["loops_blocked"]),
        "loops_completed": str(stats["loops_completed"]),
        "estimated_tokens": html_escape(str(toks["estimated_tokens"])),
        "estimated_chars": html_escape(str(toks["estimated_chars"])),
        "token_source_label": html_escape(token_source_label),
        "session_tokens": html_escape(str(toks.get("codexbar_session_tokens") or "n/a")),
        "last_turn_tokens": html_escape(str(toks.get("last_turn_tokens") or "n/a")),
        "billed_session_cost_label": html_escape(billed_session_cost_label),
        "billed_project_cost_label": html_escape(billed_project_cost_label),
        "api_equivalent_session_cost_label": html_escape(api_equivalent_session_cost_label),
        "api_equivalent_project_cost_label": html_escape(api_equivalent_project_cost_label),
        "baseline_tokens": html_escape(str(toks.get("project_cost_baseline_tokens") or 0)),
        "delta_tokens": html_escape(str(toks.get("project_cost_delta_tokens") or 0)),
        "projection_seq": str(projection_seq),
        "projection_warning_count": str(len(projection_warnings)),
        "monitor_warning_lines": monitor_warning_lines,
        "monitor_status": html_escape(monitor_status),
        "monitor_policy": html_escape(monitor_policy),
        "monitor_watch_pid": str(monitor_watch_pid),
        "monitor_watch_state": "alive" if monitor_watch_alive else "stopped",
        "monitor_server_pid": str(monitor_server_pid),
        "monitor_server_state": "alive" if monitor_server_alive else "stopped",
        "monitor_server_url": html_escape(monitor_server_url or "(no live server URL)"),
        "monitor_cleanup_status": html_escape(monitor_cleanup_status),
        "cost_source_label": html_escape(cost_source_label),
        "cost_confidence": html_escape(cost_confidence),
        "billing_confidence": billing_confidence,
        "rate_model_key": rate_model_key,
        "rate_resolution": rate_resolution,
        "billing_reason": billing_reason,
        "github_sync_state": "enabled" if gh["enabled"] else "disabled",
        "github_repo": html_escape(str(gh.get("repo") or "")),
        "orchestration_path": html_escape(str(orchestration.get("path") or "outputs/orchestration.json")),
        "groups_block": groups_block,
        "critical_path_block": critical_path_block,
        "subagents_path": html_escape(str(subagents.get("path") or "logs/agents.jsonl")),
        "subagents_note": html_escape(str(subagents.get("telemetry_note") or "")),
        "recent_events_block": recent_events_block,
        "dispatch_path": html_escape(str(dispatch.get("path") or "logs/subagent-dispatch.jsonl")),
        "dispatch_execution_path": html_escape(str(dispatch.get("execution_path") or "outputs/orchestration-execution.json")),
        "dispatch_note": html_escape(dispatch_note),
        "dispatch_summary_block": dispatch_summary_block,
        "spend_table_title": html_escape(spend_table_title),
        "wi_spend_rows_html": "".join(wi_spend_rows),
        "ws_cards_html": "".join(ws_cards) if ws_cards else "<p class='muted'>(no workstreams)</p>",
        "waves_block": waves_block,
        "ticker_items_html": ticker_items_html,
        "ticker_track_class": ticker_track_class,
        "ticker_duration": ticker_duration,
        "jobs_at_risk": str(jobs_at_risk),
        "billing_plan_label": html_escape(billing_plan_label),
        "active_jobs_html": render_focus_list(active_records, empty_text="No jobs are currently in progress."),
        "attention_jobs_html": render_focus_list(
            attention_records,
            empty_text="Nothing is currently blocked or failing truth/reward gates.",
        ),
        "attention_summary": html_escape(attention_summary),
        "next_action_title": html_escape(next_action_title),
        "next_action_summary": html_escape(next_action_summary),
        "next_action_html": next_action_html,
    }

    return (
        f"<!doctype html>\n"
        f"<html lang=\"en\" data-generated-at=\"{generated_at}\" "
        f"data-project-status=\"{html_escape(str(proj.get('status') or ''))}\" "
        f"data-monitor-status=\"{html_escape(monitor_status)}\" "
        f"data-monitor-cleanup-status=\"{html_escape(monitor_cleanup_status)}\">\n"
        "<head>\n"
        "  <meta charset=\"utf-8\">\n"
        "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        "  <title>TheWorkshop Dashboard</title>\n"
        f"  <style>{_render_dashboard_css()}</style>\n"
        "</head>\n"
        "<body>\n"
        f"{_render_dashboard_layout(content)}\n"
        f"<script>{_render_dashboard_js()}</script>\n"
        "</body>\n"
        "</html>\n"
    )


def render_md(payload: dict) -> str:
    proj = payload["project"]
    stats = payload["stats"]
    logs = payload["execution_logs"]
    toks = payload["tokens"]
    gh = payload["github_sync"]
    truth = payload.get("truth_summary") or {}
    orchestration = payload.get("orchestration") or {}
    subagents = payload.get("subagents") or {}
    dispatch = payload.get("dispatch") or {}
    projection_seq = int(payload.get("projection_seq") or 0)
    projection_warnings = payload.get("projection_warnings") if isinstance(payload.get("projection_warnings"), list) else []
    monitor_state = payload.get("monitor_state") if isinstance(payload.get("monitor_state"), dict) else {}
    sub_counts = (subagents.get("counts") or {}) if isinstance(subagents, dict) else {}
    dispatch_counts = (dispatch.get("counts") or {}) if isinstance(dispatch, dict) else {}

    lines = []
    lines.append("# TheWorkshop Dashboard")
    lines.append("")
    lines.append(f"- Generated: {payload['generated_at']}")
    lines.append(f"- Project: `{proj['id']}` {proj['title']} ({proj['status']})")
    lines.append(f"- Agreement: {proj.get('agreement_status', '')}")
    lines.append(f"- Elapsed: {proj.get('elapsed', 'n/a')}")
    lines.append("")
    lines.append("## Status")
    lines.append(f"- Workstreams: {stats['workstreams_total']}")
    lines.append(f"- Jobs: {stats['jobs_total']}")
    lines.append(f"- Planned: {stats['jobs_status']['planned']}")
    lines.append(f"- In progress: {stats['jobs_status']['in_progress']}")
    lines.append(f"- Blocked: {stats['jobs_status']['blocked']}")
    lines.append(f"- Done: {stats['jobs_status']['done']}")
    lines.append(f"- Loop jobs: enabled={stats['loops_enabled']} active={stats['loops_active']} completed={stats['loops_completed']} blocked={stats['loops_blocked']} stopped={stats['loops_stopped']} error={stats['loops_error']}")
    lines.append("")
    lines.append("## TruthGate")
    lines.append(f"- pass: {int(truth.get('pass') or 0)}")
    lines.append(f"- fail: {int(truth.get('fail') or 0)}")
    lines.append(f"- unknown: {int(truth.get('unknown') or 0)}")
    lines.append(f"- stale dependencies: {int(truth.get('stale_dependency_count') or 0)}")
    lines.append("")
    lines.append("## Runtime")
    lines.append(f"- Commands: {logs['commands']}")
    lines.append(f"- Failures: {logs['failures']}")
    lines.append(f"- Avg command duration: {logs['avg_duration_sec']:.2f}s")
    lines.append("")
    lines.append("## Sub-Agents")
    lines.append(f"- active: {int(sub_counts.get('active') or 0)}")
    lines.append(f"- completed: {int(sub_counts.get('completed') or 0)}")
    lines.append(f"- failed: {int(sub_counts.get('failed') or 0)}")
    lines.append(f"- source: {subagents.get('path') or 'logs/agents.jsonl'}")
    sub_note = str(subagents.get("telemetry_note") or "").strip()
    if sub_note:
        lines.append(f"- telemetry: {sub_note}")
    lines.append("- recent events:")
    recent_events = subagents.get("recent_events") or []
    if recent_events:
        for evt in recent_events:
            ts = str(evt.get("timestamp") or "")
            line = str(evt.get("display_text") or "").strip()
            if ts:
                line = f"{ts} - {line}" if line else ts
            severity = str(evt.get("display_severity") or "info").strip()
            if line:
                line = f"[{severity}] {line}"
            lines.append(f"  - {line}")
    else:
        lines.append("  - (none)")
    lines.append("")
    lines.append("## Dispatch Engine")
    dispatch_mode = str(dispatch.get("mode") or "not_used")
    lines.append(f"- mode: {dispatch_mode}")
    if dispatch_mode == "not_used":
        lines.append("- status: not used in this run")
    else:
        lines.append(f"- active: {int(dispatch_counts.get('active') or 0)}")
        lines.append(f"- completed: {int(dispatch_counts.get('completed') or 0)}")
        lines.append(f"- failed: {int(dispatch_counts.get('failed') or 0)}")
        lines.append(f"- blocked: {int(dispatch_counts.get('blocked') or 0)}")
    dispatch_note = str(dispatch.get("telemetry_note") or "").strip()
    if dispatch_note:
        lines.append(f"- telemetry: {dispatch_note}")
    display_summary = str(dispatch.get("display_summary") or "").strip()
    if display_summary:
        lines.append(f"- summary: {display_summary}")
    lines.append(f"- source: {dispatch.get('path') or 'logs/subagent-dispatch.jsonl'}")
    lines.append(f"- execution summary: {dispatch.get('execution_path') or 'outputs/orchestration-execution.json'}")
    lines.append("")
    lines.append("## Orchestration")
    lines.append(f"- source: {orchestration.get('path') or 'outputs/orchestration.json'}")
    lines.append(f"- stale dependencies: {int(orchestration.get('stale_dependency_count') or 0)}")
    lines.append("- parallel groups:")
    groups = orchestration.get("parallel_groups") or []
    if groups:
        for idx, group in enumerate(groups):
            members = [str(m).strip() for m in group if str(m).strip()]
            if not members:
                continue
            lines.append(f"  - Group {idx + 1}: {', '.join(members)}")
    else:
        lines.append("  - (none)")
    critical_path = [str(m).strip() for m in (orchestration.get("critical_path") or []) if str(m).strip()]
    critical_hours = float(orchestration.get("critical_path_hours") or 0.0)
    if critical_path:
        lines.append(f"- critical path: {' -> '.join(critical_path)} ({critical_hours:.2f}h)")
    else:
        lines.append("- critical path: (none)")
    lines.append("")
    lines.append("## Projection")
    lines.append(f"- sequence: {projection_seq}")
    if projection_warnings:
        lines.append("- warnings:")
        for item in projection_warnings:
            lines.append(f"  - {item}")
    else:
        lines.append("- warnings: (none)")
    lines.append("")
    lines.append("## Monitor Runtime")
    lines.append(f"- status: {monitor_state.get('status') or 'unknown'}")
    lines.append(f"- policy: {monitor_state.get('policy') or 'always'}")
    lines.append(f"- watch_pid: {monitor_state.get('watch_pid') or 0}")
    lines.append(f"- watch_alive: {bool(monitor_state.get('watch_alive'))}")
    lines.append("")
    lines.append("## Tokens")
    lines.append(f"- Estimated tokens: {toks['estimated_tokens']} ({toks['estimated_chars']} chars proxy)")
    lines.append(f"- Source: {toks.get('token_source') or 'none'}")
    lines.append(f"- Billing mode: {toks.get('billing_mode') or 'unknown'}")
    lines.append(f"- Billing confidence: {toks.get('billing_confidence') or 'low'}")
    lines.append(f"- Billing reason: {toks.get('billing_reason') or ''}")
    lines.append(f"- Session tokens: {toks.get('codexbar_session_tokens')}")
    lines.append(f"- Last turn tokens: {toks.get('last_turn_tokens')}")
    lines.append(f"- Cost source: {toks.get('cost_source') or 'none'}")
    lines.append(f"- Cost confidence: {toks.get('cost_confidence') or 'none'}")
    lines.append(f"- Billed session cost USD: {toks.get('billed_session_cost_usd')}")
    lines.append(f"- API-equivalent session cost USD: {toks.get('api_equivalent_session_cost_usd')}")
    lines.append(f"- Billed project cost USD: {toks.get('billed_project_cost_usd')}")
    lines.append(f"- API-equivalent project cost USD: {toks.get('api_equivalent_project_cost_usd')}")
    lines.append(f"- Primary cost label: {toks.get('display_cost_primary_label') or ''}")
    lines.append(f"- Secondary cost label: {toks.get('display_cost_secondary_label') or ''}")
    lines.append(f"- Estimated session cost USD: {toks.get('estimated_session_cost_usd')}")
    lines.append(f"- Estimated project cost USD: {toks.get('estimated_project_cost_usd')}")
    lines.append(f"- Baseline tokens: {toks.get('project_cost_baseline_tokens')}")
    lines.append(f"- Project token delta: {toks.get('project_cost_delta_tokens')}")
    lines.append(f"- Rate model key: {toks.get('rate_model_key') or ''}")
    lines.append(f"- Rate resolution: {toks.get('rate_resolution') or ''}")
    if toks.get("session_log_path"):
        lines.append(f"- Session log path: {toks.get('session_log_path')}")
    cost_breakdown = toks.get("cost_breakdown") if isinstance(toks.get("cost_breakdown"), dict) else {}
    if cost_breakdown:
        lines.append("- Cost breakdown (USD):")
        lines.append(f"  - input_uncached: {cost_breakdown.get('input_uncached')}")
        lines.append(f"  - cached_input: {cost_breakdown.get('cached_input')}")
        lines.append(f"  - output: {cost_breakdown.get('output')}")
        lines.append(f"  - reasoning_output: {cost_breakdown.get('reasoning_output')}")
    lines.append(
        "- API-equivalent spend by work item (estimated):"
        if str(toks.get("billing_mode") or "unknown") == "subscription_auth"
        else "- Estimated spend by work item:"
    )
    by_wi = toks.get("by_work_item") if isinstance(toks.get("by_work_item"), list) else []
    if by_wi:
        for row in by_wi:
            if not isinstance(row, dict):
                continue
            task = str(row.get("display_work_item") or row.get("work_item_id") or "Unlinked task")
            lines.append(
                f"  - {task}: ${float(row.get('estimated_cost_usd') or 0.0):.4f} "
                f"(weight={row.get('weight_basis')}, tokens={row.get('tokens_allocated')})"
            )
        lines.append(
            f"  - (unattributed): ${float(toks.get('unattributed_cost_usd') or 0.0):.4f} "
            f"(tokens={toks.get('unattributed_tokens_allocated')})"
        )
    else:
        lines.append("  - (none)")
    lines.append("")
    lines.append("## GitHub")
    lines.append(f"- Enabled: {gh['enabled']}")
    lines.append(f"- Repo: {gh.get('repo') or ''}")
    lines.append(f"- Last sync: {gh.get('last_sync_at') or ''}")
    lines.append("")
    lines.append("## Workstreams")
    lines.append("")
    for w in payload["workstreams"]:
        lines.append(f"### {w['id']} {w['title']} ({w['status']})")
        lines.append("")
        lines.append("| Work Item | Status | Wave | Depends On | Truth | Loop | Loop Status | Loop Mode | Loop Max | Loop Attempts | Loop Target | Loop Stop | Reward | Next Action |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for j in w["jobs"]:
            deps = ", ".join(j["depends_on"])
            truth_value = str(j.get("truth_status") or "unknown")
            snippet = str(j.get("truth_last_failure_snippet") or "").replace("|", "\\|")
            truth_cell = truth_value if not snippet else f"{truth_value}: {snippet}"
            reward = f"{j['reward_score']}/{j['reward_target']}"
            next_action = str(j["reward_next_action"]).replace("|", "\\|")
            loop_enabled = "enabled" if bool(j.get("loop_enabled")) else "disabled"
            loop_status = str(j.get("loop_status") or "idle")
            loop_mode = str(j.get("loop_mode") or "max_iterations")
            loop_max = int(j.get("loop_max_iterations") or 0)
            loop_attempts = int(j.get("loop_last_attempt") or 0)
            loop_target = str(j.get("loop_target_promise") or "n/a")
            loop_stop_reason = str(j.get("loop_stop_reason") or "n/a")
            lines.append(
                f"| {j['work_item_id']} | {j['status']} | {j['wave_id']} | {deps} | {truth_cell} | {loop_enabled} | {loop_status} | {loop_mode} | {loop_max} | {loop_attempts} | {loop_target} | {loop_stop_reason} | {reward} | {next_action} |"
            )
        if not w["jobs"]:
            lines.append("| (none) |  |  |  |  |  |  |  |  |  |  |  |  |")
        lines.append("")
    return "\n".join(lines) + "\n"


def atomic_write_text(path: Path, text: str) -> None:
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            fp.write(text)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(str(tmp), str(path))
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Build TheWorkshop mini dashboard artifacts.")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--out-json", help="Output JSON path (default: outputs/dashboard.json)")
    parser.add_argument("--out-md", help="Output Markdown path (default: outputs/dashboard.md)")
    parser.add_argument("--out-html", help="Output HTML path (default: outputs/dashboard.html)")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    payload = build_payload(project_root)

    out_dir = project_root / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = Path(args.out_json).expanduser().resolve() if args.out_json else out_dir / "dashboard.json"
    out_md = Path(args.out_md).expanduser().resolve() if args.out_md else out_dir / "dashboard.md"
    out_html = Path(args.out_html).expanduser().resolve() if args.out_html else out_dir / "dashboard.html"

    atomic_write_text(out_json, json.dumps(payload, indent=2) + "\n")
    atomic_write_text(out_md, render_md(payload))
    atomic_write_text(out_html, render_html(payload))

    print(str(out_html))


if __name__ == "__main__":
    main()
