#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
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
    if any(k in token for k in ("fail", "error", "cancel", "timeout")):
        return "failed"
    if any(k in token for k in ("complete", "done", "success", "pass", "finish")):
        return "completed"
    if any(k in token for k in ("active", "running", "in_progress", "start", "queue", "dispatch", "launch")):
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


def read_subagents(project_root: Path, *, recent_limit: int = 12) -> dict:
    path = project_root / "logs" / "agents.jsonl"
    if not path.exists():
        return {
            "present": False,
            "path": str(path.relative_to(project_root)),
            "counts": {"active": 0, "completed": 0, "failed": 0},
            "recent_events": [],
        }

    latest_by_agent: dict[str, str] = {}
    parsed_events: list[dict[str, str]] = []

    for idx, ln in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines()):
        if not ln.strip():
            continue
        try:
            entry = json.loads(ln)
        except Exception:
            continue
        if not isinstance(entry, dict):
            continue

        status, raw_event = parse_subagent_event(entry)
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
                "work_item_id": str(entry.get("work_item_id") or ""),
                "event": raw_event or str(entry.get("event") or ""),
                "status": status or "unknown",
                "message": truncate_text(message, limit=160),
            }
        )

    counts = {
        "active": sum(1 for s in latest_by_agent.values() if s == "active"),
        "completed": sum(1 for s in latest_by_agent.values() if s == "completed"),
        "failed": sum(1 for s in latest_by_agent.values() if s == "failed"),
    }
    recent_events = parsed_events[-recent_limit:] if parsed_events else []
    return {
        "present": True,
        "path": str(path.relative_to(project_root)),
        "counts": counts,
        "recent_events": recent_events,
    }


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
    subagents = read_subagents(project_root)
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
    sub_counts = (subagents.get("counts") or {}) if isinstance(subagents, dict) else {}

    ws_cards = []
    for w in ws:
        rows = []
        for j in w["jobs"]:
            truth_status = str(j.get("truth_status") or "unknown")
            truth_snippet = str(j.get("truth_last_failure_snippet") or "")
            truth_text = f"<span class='truth-pill {truth_class(truth_status)}'>{html_escape(truth_status)}</span>"
            if truth_snippet:
                truth_text += f"<div class='muted'>{html_escape(truth_snippet)}</div>"

            loop_enabled = "enabled" if bool(j.get("loop_enabled")) else "disabled"
            loop_status = str(j.get("loop_status") or "idle")
            loop_state_class = loop_status_class(loop_status)
            loop_mode = str(j.get("loop_mode") or "max_iterations")
            loop_attempts = int(j.get("loop_last_attempt") or 0)
            loop_max = int(j.get("loop_max_iterations") or 0)
            loop_stop_reason = str(j.get("loop_stop_reason") or "n/a")
            loop_target = str(j.get("loop_target_promise") or "")
            loop_target_display = f"target={html_escape(loop_target)}" if loop_target else "target=<none>"

            rows.append(
                "<tr>"
                f"<td>{html_escape(j['work_item_id'])}</td>"
                f"<td>{html_escape(j['title'])}</td>"
                f"<td><span class='pill {status_class(j['status'])}'>{html_escape(j['status'])}</span></td>"
                f"<td>{html_escape(j['wave_id'])}</td>"
                f"<td>{html_escape(', '.join(j['depends_on']))}</td>"
                f"<td>{truth_text}</td>"
                f"<td>{loop_enabled}</td>"
                f"<td><span class='pill {loop_state_class}'>{html_escape(loop_status)}</span></td>"
                f"<td>{html_escape(loop_mode)}</td>"
                f"<td>{loop_max}</td>"
                f"<td>{loop_attempts}</td>"
                f"<td>{loop_target_display}</td>"
                f"<td>{html_escape(loop_stop_reason)}</td>"
                f"<td>{j['reward_score']}/{j['reward_target']}</td>"
                f"<td>{html_escape(j['reward_next_action'])}</td>"
                "</tr>"
            )
        if not rows:
            rows = ["<tr><td colspan='14' class='muted'>(no jobs)</td></tr>"]
        ws_cards.append(
            "<section class='card'>"
            f"<h3>{html_escape(w['id'])}: {html_escape(w['title'])} "
            f"<span class='pill {status_class(w['status'])}'>{html_escape(w['status'])}</span></h3>"
            f"<p class='muted'>Depends on: {html_escape(', '.join(w['depends_on'])) or '(none)'}</p>"
            "<table>"
            "<thead><tr><th>WI</th><th>Title</th><th>Status</th><th>Wave</th><th>Depends On</th><th>Truth</th>"
            "<th>Loop</th><th>Loop Status</th><th>Loop Mode</th><th>Loop Max</th><th>Loop Attempts</th><th>Loop Target</th><th>Loop Stop</th><th>Reward</th><th>Next Action</th></tr></thead>"
            "<tbody>"
            + "".join(rows)
            + "</tbody></table></section>"
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
    billing_reason = str(toks.get("billing_reason") or "")
    billing_confidence = str(toks.get("billing_confidence") or "low")
    rate_model_key = str(toks.get("rate_model_key") or "")
    rate_resolution = str(toks.get("rate_resolution") or "")
    wi_spend_items = toks.get("by_work_item") if isinstance(toks.get("by_work_item"), list) else []
    wi_spend_rows: list[str] = []
    for row in wi_spend_items:
        if not isinstance(row, dict):
            continue
        wi_id = str(row.get("work_item_id") or "")
        wi_cost = fmt_usd(row.get("estimated_cost_usd"))
        wi_weight = str(row.get("weight_basis") or "")
        wi_tokens = str(row.get("tokens_allocated") or 0)
        wi_spend_rows.append(
            "<tr>"
            f"<td>{html_escape(wi_id)}</td>"
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
    truth_pass = int(truth.get("pass") or 0)
    truth_fail = int(truth.get("fail") or 0)
    truth_unknown = int(truth.get("unknown") or 0)
    stale_dependencies = int(truth.get("stale_dependency_count") or 0)
    sub_active = int(sub_counts.get("active") or 0)
    sub_completed = int(sub_counts.get("completed") or 0)
    sub_failed = int(sub_counts.get("failed") or 0)

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
    for evt in subagents.get("recent_events", []) or []:
        ts = str(evt.get("timestamp") or "")
        agent_id = str(evt.get("agent_id") or "")
        status = str(evt.get("status") or "")
        event_name = str(evt.get("event") or "")
        message = str(evt.get("message") or "")
        line = f"{ts} {agent_id} {status} {event_name}".strip()
        if message:
            line += f" - {message}"
        recent_event_rows.append(f"<li>{html_escape(line)}</li>")
    recent_events_block = (
        "<ul>" + "".join(recent_event_rows) + "</ul>" if recent_event_rows else "<p class='muted'>(no events)</p>"
    )

    return f"""<!doctype html>
<html lang="en" data-generated-at="{generated_at}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TheWorkshop Dashboard</title>
  <style>
    :root {{
      --bg: #f4f1ea;
      --panel: #fffdf8;
      --ink: #1f252c;
      --muted: #5f6b75;
      --line: #d7d0c4;
      --accent: #0f6b5d;
      --planned: #6b7280;
      --inprogress: #b45f06;
      --blocked: #b42318;
      --done: #027a48;
      --cancelled: #7a1f5c;
    }}
    .monitor {{
      position: sticky;
      top: 14px;
      z-index: 10;
      background: rgba(255, 253, 248, 0.88);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 10px 12px;
      backdrop-filter: blur(10px);
      display: flex;
      gap: 12px;
      align-items: center;
      justify-content: space-between;
      margin: 0 0 14px;
    }}
    .monitor .group {{
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 3px 10px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: #f1ede5;
      font-size: 12px;
      line-height: 1.6;
    }}
    .badge-on {{ border-color: rgba(15,107,93,0.35); background: rgba(15,107,93,0.10); }}
    .badge-off {{ border-color: rgba(95,107,117,0.35); background: rgba(95,107,117,0.12); }}
    .badge-stale {{
      border-color: rgba(180,35,24,0.35);
      background: rgba(180,35,24,0.10);
      color: var(--blocked);
      font-weight: 700;
      letter-spacing: .04em;
    }}
    button {{
      appearance: none;
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 6px 10px;
      background: #fff;
      color: var(--ink);
      font-size: 12px;
      cursor: pointer;
    }}
    button:hover {{ border-color: rgba(15,107,93,0.55); }}
    button:active {{ transform: translateY(1px); }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 15% 15%, #efe7d8 0%, transparent 32%),
        radial-gradient(circle at 85% 5%, #e2efe9 0%, transparent 30%),
        linear-gradient(180deg, #f8f4ed 0%, var(--bg) 70%);
      min-height: 100vh;
    }}
    .wrap {{ max-width: 1200px; margin: 0 auto; padding: 24px; }}
    h1 {{ margin: 0; font-size: 30px; letter-spacing: .2px; }}
    h2 {{ margin: 24px 0 12px; font-size: 18px; }}
    h3 {{ margin: 0 0 8px; font-size: 16px; }}
    .muted {{ color: var(--muted); }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
      margin-top: 14px;
    }}
    .card {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 14px;
      box-shadow: 0 2px 6px rgba(0,0,0,0.03);
    }}
    .pill {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 999px;
      color: white;
      font-size: 12px;
      line-height: 1.5;
      vertical-align: middle;
      margin-left: 8px;
    }}
    .st-planned {{ background: var(--planned); }}
    .st-inprogress {{ background: var(--inprogress); }}
    .st-blocked {{ background: var(--blocked); }}
    .st-done {{ background: var(--done); }}
    .st-cancelled {{ background: var(--cancelled); }}
    .truth-pill {{
      display: inline-block;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 12px;
      line-height: 1.5;
      text-transform: uppercase;
      letter-spacing: .03em;
      font-weight: 600;
    }}
    .truth-pass {{ background: rgba(2, 122, 72, 0.14); color: #03543f; }}
    .truth-fail {{ background: rgba(180, 35, 24, 0.14); color: #9a2418; }}
    .truth-unknown {{ background: rgba(95, 107, 117, 0.14); color: #3f4a54; }}
    .panel-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 12px;
      margin-top: 12px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }}
    th, td {{
      text-align: left;
      padding: 8px 6px;
      border-top: 1px solid var(--line);
      vertical-align: top;
    }}
    th {{ font-size: 12px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); }}
    ul {{ margin: 6px 0 0 18px; }}
    code {{
      background: #f1ede5;
      border: 1px solid #e0d8ca;
      border-radius: 6px;
      padding: 2px 6px;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 12px;
    }}
  </style>
</head>
<body>
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
        <span class="muted">generated <code id="twGeneratedAt">{generated_at}</code></span>
      </div>
    </div>

    <h1>TheWorkshop Dashboard</h1>
    <p class="muted"><b>{html_escape(proj['id'])}</b> {html_escape(proj['title'])}
      <span class="pill {status_class(proj['status'])}">{html_escape(proj['status'])}</span>
      | generated {html_escape(payload['generated_at'])}
    </p>

    <section class="grid">
      <div class="card"><h3>Agreement</h3><p>{html_escape(proj.get('agreement_status',''))}</p></div>
      <div class="card"><h3>Elapsed</h3><p>{html_escape(proj.get('elapsed','n/a'))}</p></div>
      <div class="card"><h3>Workstreams</h3><p>{stats['workstreams_total']}</p></div>
      <div class="card"><h3>Jobs</h3><p>{stats['jobs_total']}</p></div>
      <div class="card"><h3>In Progress</h3><p>{stats['jobs_status']['in_progress']}</p></div>
      <div class="card"><h3>Blocked</h3><p>{stats['jobs_status']['blocked']}</p></div>
      <div class="card"><h3>Done</h3><p>{stats['jobs_status']['done']}</p></div>
      <div class="card"><h3>Loop Jobs</h3>
        <p>enabled: {stats['loops_enabled']}</p>
        <p class="muted">active {stats['loops_active']} | completed {stats['loops_completed']} | blocked {stats['loops_blocked']} | stopped {stats['loops_stopped']} | error {stats['loops_error']}</p>
      </div>
      <div class="card"><h3>Truth Status</h3><p>pass {truth_pass} | fail {truth_fail} | unknown {truth_unknown}</p></div>
      <div class="card"><h3>Stale Dependencies</h3><p>{stale_dependencies}</p></div>
      <div class="card"><h3>Sub-Agents</h3><p>active {sub_active} | completed {sub_completed} | failed {sub_failed}</p></div>
      <div class="card"><h3>Commands / Failures</h3><p>{logs['commands']} / {logs['failures']}</p></div>
      <div class="card"><h3>Avg Command Duration</h3><p>{logs['avg_duration_sec']:.2f}s</p></div>
      <div class="card"><h3>Estimated Tokens</h3><p>{toks['estimated_tokens']}</p><p class="muted">{toks['estimated_chars']} chars proxy</p></div>
      <div class="card"><h3>Token Source</h3><p>{html_escape(token_source_label)}</p>
        <p class="muted">session tokens: {html_escape(str(toks.get('codexbar_session_tokens') or 'n/a'))}</p>
        <p class="muted">last turn: {html_escape(str(toks.get('last_turn_tokens') or 'n/a'))}</p>
      </div>
      <div class="card"><h3>Session Cost</h3>
        <p>{html_escape(billed_session_cost_label)} billed</p>
        <p class="muted">API-equivalent: {html_escape(api_equivalent_session_cost_label)}</p>
        <p class="muted">plan: {'Codex auth/subscription' if billing_mode == 'subscription_auth' else 'metered API' if billing_mode == 'metered_api' else 'unknown'}</p>
        <p class="muted">source: {html_escape(cost_source_label)} ({html_escape(cost_confidence)})</p>
        <p class="muted">billing confidence: {html_escape(billing_confidence)}</p>
        <p class="muted">model: {html_escape(rate_model_key or 'n/a')}</p>
      </div>
      <div class="card"><h3>Project Cost (Delta)</h3>
        <p>{html_escape(billed_project_cost_label)} billed delta</p>
        <p class="muted">API-equivalent delta: {html_escape(api_equivalent_project_cost_label)}</p>
        <p class="muted">baseline tokens: {html_escape(str(toks.get('project_cost_baseline_tokens') or 0))}</p>
        <p class="muted">delta tokens: {html_escape(str(toks.get('project_cost_delta_tokens') or 0))}</p>
      </div>
      <div class="card"><h3>GitHub Sync</h3><p>{'enabled' if gh['enabled'] else 'disabled'}</p>
        <p class="muted">{html_escape(gh.get('repo') or '')}</p>
      </div>
    </section>

    {waves_block}

    <section class="panel-grid">
      <section class="card">
        <h3>Orchestration</h3>
        <p class="muted">source: {html_escape(str(orchestration.get('path') or 'outputs/orchestration.json'))}</p>
        <p><b>Parallel Groups</b></p>
        {groups_block}
        <p><b>Critical Path</b></p>
        {critical_path_block}
      </section>
      <section class="card">
        <h3>Sub-Agents</h3>
        <p>active {sub_active} | completed {sub_completed} | failed {sub_failed}</p>
        <p class="muted">source: {html_escape(str(subagents.get('path') or 'logs/agents.jsonl'))}</p>
        <p><b>Recent Events</b></p>
        {recent_events_block}
      </section>
    </section>

    <section class="panel-grid">
      <section class="card">
        <h3>{html_escape(spend_table_title)}</h3>
        <p class="muted">{html_escape(rate_resolution or 'rate resolution unavailable')}</p>
        <p class="muted">{html_escape(billing_reason or '')}</p>
        <table>
          <thead><tr><th>Work Item</th><th>Estimated Cost</th><th>Weight</th><th>Tokens Allocated</th></tr></thead>
          <tbody>
            {''.join(wi_spend_rows)}
          </tbody>
        </table>
      </section>
    </section>

    <h2>Workstreams & Jobs</h2>
    {''.join(ws_cards) if ws_cards else '<p class="muted">(no workstreams)</p>'}

    <section class="card">
      <h3>Paths</h3>
      <ul>
        <li><code>outputs/dashboard.json</code></li>
        <li><code>outputs/dashboard.md</code></li>
        <li><code>outputs/dashboard.html</code></li>
      </ul>
    </section>
  </div>
  <script>
  // TheWorkshop auto-refresh controller (file:// safe via cache-busting query param).
  (function () {{
    var REFRESH_MS = 5000;
    // For file-based dashboards, "generated_at" only updates when the agent rebuilds the dashboard.
    // Use a practical stale threshold so the UI doesn't scream STALE during normal multi-minute work.
    var STALE_AFTER_MS = Math.max(5 * 60 * 1000, 2 * REFRESH_MS);
    var LS_KEY = "theworkshop.autorefresh.enabled";
    var SS_SCROLL_KEY = "theworkshop.autorefresh.scrollY";

    function lsGet(key, fallback) {{
      try {{ return window.localStorage.getItem(key) || fallback; }} catch (e) {{ return fallback; }}
    }}
    function lsSet(key, value) {{
      try {{ window.localStorage.setItem(key, value); }} catch (e) {{}}
    }}
    function ssGet(key, fallback) {{
      try {{ return window.sessionStorage.getItem(key) || fallback; }} catch (e) {{ return fallback; }}
    }}
    function ssSet(key, value) {{
      try {{ window.sessionStorage.setItem(key, value); }} catch (e) {{}}
    }}
    function $(id) {{ return document.getElementById(id); }}
    function setText(el, text) {{ if (el) el.textContent = text; }}
    function show(el, on) {{ if (el) el.style.display = on ? "" : "none"; }}

    var enabled = lsGet(LS_KEY, "1") !== "0";
    var nextAt = Date.now() + REFRESH_MS;
    var genAtStr = document.documentElement.getAttribute("data-generated-at") || "";
    var genAtMs = Date.parse(genAtStr);

    var elToggle = $("twRefreshToggle");
    var elNow = $("twRefreshNow");
    var elCountdown = $("twRefreshCountdown");
    var elStatus = $("twRefreshStatus");
    var elStale = $("twStaleBadge");
    var elAge = $("twDataAge");

    function saveScroll() {{
      try {{ ssSet(SS_SCROLL_KEY, String(window.scrollY || 0)); }} catch (e) {{}}
    }}

    function restoreScroll() {{
      var y = parseInt(ssGet(SS_SCROLL_KEY, "0"), 10);
      if (!isNaN(y) && y > 0) {{
        window.scrollTo(0, y);
      }}
    }}

    function reloadNow() {{
      saveScroll();
      var base = window.location.href.split("?")[0];
      window.location.replace(base + "?t=" + Date.now());
    }}

    function fmtAge(seconds) {{
      var s = Math.max(0, Math.floor(seconds));
      var m = Math.floor(s / 60);
      var r = s % 60;
      if (m <= 0) return s + "s";
      return m + "m " + r + "s";
    }}

    function render() {{
      if (elStatus) {{
        elStatus.textContent = enabled ? "ON" : "PAUSED";
        elStatus.className = enabled ? "badge badge-on" : "badge badge-off";
      }}
      if (elToggle) {{
        elToggle.textContent = enabled ? "Pause" : "Resume";
      }}
    }}

    function tick() {{
      var now = Date.now();

      if (!isNaN(genAtMs)) {{
        setText(elAge, fmtAge((now - genAtMs) / 1000));
      }}
      if (!isNaN(genAtMs) && (now - genAtMs) > STALE_AFTER_MS) {{
        show(elStale, true);
      }} else {{
        show(elStale, false);
      }}

      if (!enabled) {{
        setText(elCountdown, "paused");
        return;
      }}

      var remaining = Math.max(0, nextAt - now);
      setText(elCountdown, Math.ceil(remaining / 1000) + "s");
      if (now >= nextAt) {{
        reloadNow();
      }}
    }}

    if (elToggle) {{
      elToggle.addEventListener("click", function () {{
        enabled = !enabled;
        lsSet(LS_KEY, enabled ? "1" : "0");
        nextAt = Date.now() + REFRESH_MS;
        render();
        tick();
      }});
    }}
    if (elNow) {{
      elNow.addEventListener("click", function () {{
        reloadNow();
      }});
    }}

    render();
    tick();
    restoreScroll();
    window.addEventListener("beforeunload", saveScroll);
    window.setInterval(tick, 250);
  }})();
  </script>
</body>
</html>
"""


def render_md(payload: dict) -> str:
    proj = payload["project"]
    stats = payload["stats"]
    logs = payload["execution_logs"]
    toks = payload["tokens"]
    gh = payload["github_sync"]
    truth = payload.get("truth_summary") or {}
    orchestration = payload.get("orchestration") or {}
    subagents = payload.get("subagents") or {}
    sub_counts = (subagents.get("counts") or {}) if isinstance(subagents, dict) else {}

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
    lines.append("- recent events:")
    recent_events = subagents.get("recent_events") or []
    if recent_events:
        for evt in recent_events:
            ts = str(evt.get("timestamp") or "")
            agent_id = str(evt.get("agent_id") or "")
            status = str(evt.get("status") or "")
            event_name = str(evt.get("event") or "")
            msg = str(evt.get("message") or "")
            line = f"{ts} {agent_id} {status} {event_name}".strip()
            if msg:
                line += f" - {msg}"
            lines.append(f"  - {line}")
    else:
        lines.append("  - (none)")
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
            lines.append(
                f"  - {row.get('work_item_id')}: ${float(row.get('estimated_cost_usd') or 0.0):.4f} "
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
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


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
