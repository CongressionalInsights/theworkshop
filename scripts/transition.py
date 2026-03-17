#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from plan_sync import sync_project_plans
from tw_tools import append_section_bullet, run_script
from twlib import (
    STATUS_VALUES,
    list_job_dirs,
    list_workstream_dirs,
    load_workstream,
    now_iso,
    read_md,
    resolve_project_root,
    today_yyyymmdd,
    write_md,
)


@dataclass
class EntityRef:
    kind: str
    entity_id: str
    plan_path: Path


@dataclass
class TransitionResult:
    transition_id: str
    timestamp: str
    primary: EntityRef
    primary_from: str
    primary_to: str
    changed_entities: list[dict[str, str]]
    promise: str


def _session_id() -> str:
    for key in ("THEWORKSHOP_SESSION_ID", "TERM_SESSION_ID", "ITERM_SESSION_ID", "CODEX_THREAD_ID"):
        val = str(os.environ.get(key) or "").strip()
        if val:
            return val
    return "unknown"


def _next_transition_id(project_root: Path, ts: str) -> str:
    events_path = project_root / "logs" / "events.jsonl"
    date_part = today_yyyymmdd()
    max_n = 0
    if events_path.exists():
        try:
            for raw in events_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                if not raw.strip():
                    continue
                item = json.loads(raw)
                tid = str(item.get("transition_id") or "").strip()
                if not tid.startswith(f"TR-{date_part}-"):
                    continue
                tail = tid.rsplit("-", 1)[-1]
                try:
                    max_n = max(max_n, int(tail))
                except Exception:
                    continue
        except Exception:
            pass
    return f"TR-{date_part}-{max_n + 1:04d}"


def _find_workstream_dir(project_root: Path, ws_id: str) -> Path:
    ws_id = ws_id.strip()
    if not ws_id:
        raise SystemExit("workstream transition requires --entity-id WS-...")
    for ws_dir in list_workstream_dirs(project_root):
        plan_path = ws_dir / "plan.md"
        try:
            ws_doc = read_md(plan_path)
            actual = str(ws_doc.frontmatter.get("id") or "").strip()
        except Exception:
            actual = ""
        if actual == ws_id or ws_dir.name.startswith(ws_id):
            return ws_dir
    raise SystemExit(f"Workstream not found: {ws_id}")


def _find_job_dir(project_root: Path, wi_id: str) -> Path:
    wi_id = wi_id.strip()
    if not wi_id:
        raise SystemExit("job transition requires --entity-id WI-...")
    matches = list(project_root.glob(f"workstreams/WS-*/jobs/{wi_id}-*"))
    if len(matches) != 1:
        raise SystemExit(f"Expected exactly one job directory for {wi_id}, got {len(matches)}")
    return matches[0]


def _entity_ref(project_root: Path, kind: str, entity_id: str | None) -> EntityRef:
    k = kind.strip().lower()
    if k == "project":
        plan_path = project_root / "plan.md"
        proj_doc = read_md(plan_path)
        actual_id = str(proj_doc.frontmatter.get("id") or "").strip()
        resolved_id = str(entity_id or actual_id).strip() or "PROJECT"
        if entity_id and actual_id and resolved_id != actual_id:
            raise SystemExit(f"Project id mismatch: requested {resolved_id}, found {actual_id}")
        return EntityRef(kind="project", entity_id=resolved_id, plan_path=plan_path)
    if k == "workstream":
        ws_dir = _find_workstream_dir(project_root, str(entity_id or ""))
        ws_doc = read_md(ws_dir / "plan.md")
        ws_id = str(ws_doc.frontmatter.get("id") or ws_dir.name).strip()
        return EntityRef(kind="workstream", entity_id=ws_id, plan_path=ws_dir / "plan.md")
    if k == "job":
        job_dir = _find_job_dir(project_root, str(entity_id or ""))
        job_doc = read_md(job_dir / "plan.md")
        wi_id = str(job_doc.frontmatter.get("work_item_id") or job_dir.name).strip()
        return EntityRef(kind="job", entity_id=wi_id, plan_path=job_dir / "plan.md")
    raise SystemExit(f"Unsupported entity kind: {kind}")


def _append_event(project_root: Path, payload: dict[str, Any]) -> None:
    events_path = project_root / "logs" / "events.jsonl"
    events_path.parent.mkdir(parents=True, exist_ok=True)
    with events_path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload, separators=(",", ":")) + "\n")


def _write_snapshot_backfill(project_root: Path, *, actor: str, reason: str) -> None:
    events_path = project_root / "logs" / "events.jsonl"
    if events_path.exists() and events_path.stat().st_size > 0:
        return
    ts = now_iso()
    proj_doc = read_md(project_root / "plan.md")
    snapshot = {
        "schema": "theworkshop.transition.v1",
        "event": "snapshot",
        "transition_id": f"TR-{today_yyyymmdd()}-0000",
        "timestamp": ts,
        "actor": actor,
        "reason": reason,
        "project": {
            "id": str(proj_doc.frontmatter.get("id") or "").strip(),
            "status": str(proj_doc.frontmatter.get("status") or "planned").strip(),
        },
        "workstreams": [],
        "jobs": [],
    }
    for ws_dir in list_workstream_dirs(project_root):
        ws_doc = read_md(ws_dir / "plan.md")
        ws_id = str(ws_doc.frontmatter.get("id") or ws_dir.name).strip()
        ws_status = str(ws_doc.frontmatter.get("status") or "planned").strip()
        snapshot["workstreams"].append({"id": ws_id, "status": ws_status})
        for job_dir in list_job_dirs(ws_dir):
            jdoc = read_md(job_dir / "plan.md")
            wi_id = str(jdoc.frontmatter.get("work_item_id") or job_dir.name).strip()
            snapshot["jobs"].append({"id": wi_id, "status": str(jdoc.frontmatter.get("status") or "planned").strip()})
    _append_event(project_root, snapshot)


def _ensure_project_defaults(project_root: Path, *, ts: str) -> None:
    plan_path = project_root / "plan.md"
    doc = read_md(plan_path)
    changed = False
    if str(doc.frontmatter.get("monitor_open_policy") or "").strip() not in {"always", "once", "manual"}:
        doc.frontmatter["monitor_open_policy"] = "once"
        changed = True
    if "monitor_session_id" not in doc.frontmatter:
        doc.frontmatter["monitor_session_id"] = ""
        changed = True
    if "last_transition_id" not in doc.frontmatter:
        doc.frontmatter["last_transition_id"] = ""
        changed = True
    if changed:
        doc.frontmatter["updated_at"] = ts
        write_md(plan_path, doc)


def _set_status_fields(frontmatter: dict[str, Any], *, to_status: str, ts: str) -> None:
    current_started = str(frontmatter.get("started_at") or "").strip()
    if to_status in {"in_progress", "blocked"} and not current_started:
        frontmatter["started_at"] = ts

    if to_status == "done":
        if not str(frontmatter.get("completed_at") or "").strip():
            frontmatter["completed_at"] = ts
        frontmatter["cancelled_at"] = ""
    elif to_status == "cancelled":
        frontmatter["cancelled_at"] = ts
        frontmatter["completed_at"] = ""
    else:
        frontmatter["completed_at"] = ""
        if str(frontmatter.get("cancelled_at") or "").strip():
            frontmatter["cancelled_at"] = ""


def _append_progress(plan_path: Path, *, ts: str, transition_id: str, actor: str, from_status: str, to_status: str, reason: str) -> None:
    doc = read_md(plan_path)
    line = (
        f"{ts} transition:{transition_id} actor={actor} "
        f"{from_status} -> {to_status}; reason: {reason}"
    )
    doc.body = append_section_bullet(doc.body, "# Progress Log", line)
    write_md(plan_path, doc)


def _append_project_decision(project_root: Path, *, ts: str, transition_id: str, actor: str, reason: str) -> None:
    plan_path = project_root / "plan.md"
    doc = read_md(plan_path)
    line = f"{ts} transition:{transition_id} actor={actor} reason={reason}"
    doc.body = append_section_bullet(doc.body, "# Decisions", line)
    write_md(plan_path, doc)


def _validate_done_gate(project_root: Path, entity: EntityRef) -> None:
    if entity.kind == "job":
        return
    if entity.kind == "workstream":
        ws_dir = entity.plan_path.parent
        not_done: list[str] = []
        for job_dir in list_job_dirs(ws_dir):
            jdoc = read_md(job_dir / "plan.md")
            wi = str(jdoc.frontmatter.get("work_item_id") or job_dir.name).strip()
            st = str(jdoc.frontmatter.get("status") or "planned").strip()
            if st != "done":
                not_done.append(f"{wi} ({st})")
        if not_done:
            raise SystemExit("Cannot mark workstream done; jobs not done:\n- " + "\n- ".join(not_done))
        return

    not_done_ws: list[str] = []
    for ws_dir in list_workstream_dirs(project_root):
        ws_doc = read_md(ws_dir / "plan.md")
        ws_id = str(ws_doc.frontmatter.get("id") or ws_dir.name).strip()
        ws_status = str(ws_doc.frontmatter.get("status") or "planned").strip()
        if ws_status != "done":
            not_done_ws.append(f"{ws_id} ({ws_status})")
    if not_done_ws:
        raise SystemExit("Cannot mark project done; workstreams not done:\n- " + "\n- ".join(not_done_ws))


def _collect_cancel_targets(project_root: Path, entity: EntityRef) -> list[EntityRef]:
    targets: list[EntityRef] = [entity]
    if entity.kind == "job":
        return targets

    if entity.kind == "workstream":
        ws_dir = entity.plan_path.parent
        for job_dir in list_job_dirs(ws_dir):
            jdoc = read_md(job_dir / "plan.md")
            jst = str(jdoc.frontmatter.get("status") or "planned").strip()
            if jst in {"done", "cancelled"}:
                continue
            wi = str(jdoc.frontmatter.get("work_item_id") or job_dir.name).strip()
            targets.append(EntityRef(kind="job", entity_id=wi, plan_path=job_dir / "plan.md"))
        return targets

    # project
    for ws_dir in list_workstream_dirs(project_root):
        ws_doc = read_md(ws_dir / "plan.md")
        ws_id = str(ws_doc.frontmatter.get("id") or ws_dir.name).strip()
        ws_status = str(ws_doc.frontmatter.get("status") or "planned").strip()
        if ws_status not in {"done", "cancelled"}:
            targets.append(EntityRef(kind="workstream", entity_id=ws_id, plan_path=ws_dir / "plan.md"))
        for job_dir in list_job_dirs(ws_dir):
            jdoc = read_md(job_dir / "plan.md")
            jst = str(jdoc.frontmatter.get("status") or "planned").strip()
            if jst in {"done", "cancelled"}:
                continue
            wi = str(jdoc.frontmatter.get("work_item_id") or job_dir.name).strip()
            targets.append(EntityRef(kind="job", entity_id=wi, plan_path=job_dir / "plan.md"))
    return targets


def _all_workstreams_terminal(project_root: Path) -> bool:
    workstreams = list_workstream_dirs(project_root)
    if not workstreams:
        return False
    for ws_dir in workstreams:
        ws_doc = read_md(ws_dir / "plan.md")
        ws_status = str(ws_doc.frontmatter.get("status") or "planned").strip()
        if ws_status not in {"done", "cancelled"}:
            return False
    return True


def _apply_transition(
    project_root: Path,
    *,
    entity: EntityRef,
    to_status: str,
    expected_from: str,
    transition_id: str,
    ts: str,
    actor: str,
    reason: str,
    extra_frontmatter: dict[str, Any] | None,
    extra_progress: list[str] | None,
    cascade_parent: EntityRef | None,
) -> dict[str, str]:
    doc = read_md(entity.plan_path)

    status_key = "status"
    id_key = "id"
    if entity.kind == "job":
        id_key = "work_item_id"

    from_status = str(doc.frontmatter.get(status_key) or "planned").strip()
    if expected_from and from_status != expected_from:
        raise SystemExit(
            f"Expected {entity.kind} {entity.entity_id} status={expected_from!r}, got {from_status!r}"
        )

    if from_status == to_status:
        return {
            "kind": entity.kind,
            "id": entity.entity_id,
            "path": str(entity.plan_path.relative_to(project_root)),
            "from_status": from_status,
            "to_status": to_status,
            "result": "noop",
        }

    doc.frontmatter[status_key] = to_status
    _set_status_fields(doc.frontmatter, to_status=to_status, ts=ts)

    if extra_frontmatter:
        for key, value in extra_frontmatter.items():
            doc.frontmatter[key] = value

    doc.frontmatter["updated_at"] = ts
    doc.body = append_section_bullet(
        doc.body,
        "# Progress Log",
        f"{ts} transition:{transition_id} actor={actor} {from_status} -> {to_status}; reason: {reason}",
    )
    if extra_progress:
        for line in extra_progress:
            if str(line).strip():
                doc.body = append_section_bullet(doc.body, "# Progress Log", f"{ts} {str(line).strip()}")

    write_md(entity.plan_path, doc)

    event = {
        "schema": "theworkshop.transition.v1",
        "event": "state_transition",
        "transition_id": transition_id,
        "timestamp": ts,
        "actor": actor,
        "reason": reason,
        "entity_kind": entity.kind,
        "entity_id": str(doc.frontmatter.get(id_key) or entity.entity_id),
        "path": str(entity.plan_path.relative_to(project_root)),
        "from_status": from_status,
        "to_status": to_status,
        "session_id": _session_id(),
    }
    if cascade_parent is not None:
        event["cascade_parent_kind"] = cascade_parent.kind
        event["cascade_parent_id"] = cascade_parent.entity_id
    _append_event(project_root, event)

    return {
        "kind": entity.kind,
        "id": str(doc.frontmatter.get(id_key) or entity.entity_id),
        "path": str(entity.plan_path.relative_to(project_root)),
        "from_status": from_status,
        "to_status": to_status,
        "result": "changed",
    }


def transition_entity(
    project_root: Path,
    *,
    entity_kind: str,
    entity_id: str | None,
    to_status: str,
    reason: str,
    actor: str,
    expected_from: str = "",
    cascade: bool = True,
    ts: str | None = None,
    extra_frontmatter: dict[str, Any] | None = None,
    extra_progress: list[str] | None = None,
    sync: bool = True,
    refresh_dashboard: bool = True,
    start_monitor: bool = False,
    monitor_policy_override: str = "",
    no_open: bool = False,
) -> TransitionResult:
    status = str(to_status or "").strip()
    if status not in STATUS_VALUES:
        raise SystemExit(f"Invalid --to-status {status!r}; expected one of {sorted(STATUS_VALUES)}")

    ts = ts or now_iso()
    _ensure_project_defaults(project_root, ts=ts)
    _write_snapshot_backfill(project_root, actor=actor, reason="initial transition backfill")

    target = _entity_ref(project_root, entity_kind, entity_id)
    target_doc = read_md(target.plan_path)
    target_from = str(target_doc.frontmatter.get("status") or "planned").strip()

    if status == "done":
        _validate_done_gate(project_root, target)

    transition_id = _next_transition_id(project_root, ts)
    changed: list[dict[str, str]] = []

    if status == "cancelled" and cascade:
        cancel_targets = _collect_cancel_targets(project_root, target)
        for idx, ent in enumerate(cancel_targets):
            ent_expected = expected_from if idx == 0 else ""
            ent_extra_fm = extra_frontmatter if idx == 0 else None
            ent_extra_progress = extra_progress if idx == 0 else None
            parent = None if idx == 0 else target
            changed.append(
                _apply_transition(
                    project_root,
                    entity=ent,
                    to_status="cancelled",
                    expected_from=ent_expected,
                    transition_id=transition_id,
                    ts=ts,
                    actor=actor,
                    reason=reason,
                    extra_frontmatter=ent_extra_fm,
                    extra_progress=ent_extra_progress,
                    cascade_parent=parent,
                )
            )
    else:
        changed.append(
            _apply_transition(
                project_root,
                entity=target,
                to_status=status,
                expected_from=expected_from,
                transition_id=transition_id,
                ts=ts,
                actor=actor,
                reason=reason,
                extra_frontmatter=extra_frontmatter,
                extra_progress=extra_progress,
                cascade_parent=None,
            )
        )

    proj_doc = read_md(project_root / "plan.md")
    proj_doc.frontmatter["last_transition_id"] = transition_id
    if str(proj_doc.frontmatter.get("monitor_open_policy") or "").strip() not in {"always", "once", "manual"}:
        proj_doc.frontmatter["monitor_open_policy"] = "always"
    proj_doc.frontmatter["updated_at"] = ts
    write_md(project_root / "plan.md", proj_doc)

    if status == "cancelled":
        _append_project_decision(project_root, ts=ts, transition_id=transition_id, actor=actor, reason=reason)

    if sync:
        sync_project_plans(project_root, ts=ts)

    if refresh_dashboard:
        try:
            if str(os.environ.get("THEWORKSHOP_TEST_FAIL_PROJECTOR") or "").strip() == "1":
                raise RuntimeError("forced projector failure via THEWORKSHOP_TEST_FAIL_PROJECTOR=1")
            run_script("dashboard_projector.py", ["--project", str(project_root)], check=True)
        except Exception as exc:
            _append_event(
                project_root,
                {
                    "schema": "theworkshop.transition.v1",
                    "event": "projection_warning",
                    "transition_id": transition_id,
                    "timestamp": now_iso(),
                    "actor": actor,
                    "reason": f"dashboard projector failed: {exc}",
                    "entity_kind": target.kind,
                    "entity_id": target.entity_id,
                },
            )

    terminal_cleanup = False
    if status in {"done", "cancelled"}:
        if target.kind == "project":
            terminal_cleanup = True
        elif target.kind == "workstream" and _all_workstreams_terminal(project_root):
            terminal_cleanup = True

    if terminal_cleanup:
        try:
            stop_args = [
                "stop",
                "--project",
                str(project_root),
                "--terminal-status",
                status,
                "--reason",
                reason,
            ]
            run_script("monitor_runtime.py", stop_args, check=True)
        except Exception as exc:
            _append_event(
                project_root,
                {
                    "schema": "theworkshop.transition.v1",
                    "event": "monitor_warning",
                    "transition_id": transition_id,
                    "timestamp": now_iso(),
                    "actor": actor,
                    "reason": f"monitor stop failed: {exc}",
                    "entity_kind": target.kind,
                    "entity_id": target.entity_id,
                },
            )
    elif start_monitor:
        policy_args: list[str] = ["start", "--project", str(project_root)]
        if monitor_policy_override:
            policy_args += ["--policy", monitor_policy_override]
        if no_open:
            policy_args += ["--no-open"]
        try:
            run_script("monitor_runtime.py", policy_args, check=True)
        except Exception as exc:
            _append_event(
                project_root,
                {
                    "schema": "theworkshop.transition.v1",
                    "event": "monitor_warning",
                    "transition_id": transition_id,
                    "timestamp": now_iso(),
                    "actor": actor,
                    "reason": f"monitor start failed: {exc}",
                    "entity_kind": target.kind,
                    "entity_id": target.entity_id,
                },
            )

    promise = ""
    if status == "done":
        promise = f"<promise>{target.entity_id}-DONE</promise>"
    elif status == "cancelled":
        promise = f"<promise>{target.entity_id}-CANCELLED</promise>"

    return TransitionResult(
        transition_id=transition_id,
        timestamp=ts,
        primary=target,
        primary_from=target_from,
        primary_to=status,
        changed_entities=changed,
        promise=promise,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Canonical TheWorkshop transition engine.")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--entity-kind", choices=["project", "workstream", "job"], required=True)
    parser.add_argument("--entity-id", default="", help="Entity id (optional for project)")
    parser.add_argument("--from-status", default="", help="Expected current status")
    parser.add_argument("--to-status", required=True, choices=sorted(STATUS_VALUES))
    parser.add_argument("--reason", required=True, help="Transition reason")
    parser.add_argument("--actor", default="theworkshop.transition")
    parser.add_argument("--no-cascade", action="store_true", help="Disable cancellation cascade")
    parser.add_argument("--no-sync", action="store_true", help="Skip plan sync")
    parser.add_argument("--no-dashboard", action="store_true", help="Skip dashboard projection")
    parser.add_argument("--start-monitor", action="store_true", help="Start monitor runtime after transition")
    parser.add_argument("--monitor-policy", choices=["always", "once", "manual"], default="")
    parser.add_argument("--no-open", action="store_true", help="Force monitor start in no-open mode")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    res = transition_entity(
        project_root,
        entity_kind=args.entity_kind,
        entity_id=args.entity_id or None,
        to_status=args.to_status,
        reason=args.reason,
        actor=args.actor,
        expected_from=args.from_status,
        cascade=not args.no_cascade,
        sync=not args.no_sync,
        refresh_dashboard=not args.no_dashboard,
        start_monitor=args.start_monitor,
        monitor_policy_override=args.monitor_policy,
        no_open=args.no_open,
    )

    print(json.dumps(
        {
            "transition_id": res.transition_id,
            "timestamp": res.timestamp,
            "entity_kind": res.primary.kind,
            "entity_id": res.primary.entity_id,
            "from_status": res.primary_from,
            "to_status": res.primary_to,
            "changed": res.changed_entities,
            "promise": res.promise,
        },
        indent=2,
    ))
    if res.promise:
        print(res.promise)


if __name__ == "__main__":
    main()
