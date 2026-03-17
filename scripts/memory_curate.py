#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from learning_store import (
    MEMORY_CURATION_SCHEMA,
    MEMORY_PROPOSAL_SCHEMA,
    append_memory_entries,
    global_memory_path,
    iter_staged_records,
    load_json_dict,
    memory_contains_statement,
    memory_group_fingerprint,
    memory_proposals_dir,
    project_memory_path,
    unique_values,
    write_json_dict,
)
from twlib import now_iso, resolve_project_root


def _score(record: dict[str, Any]) -> tuple[float, str, str]:
    return (
        float(record.get("confidence") or 0.0),
        str(record.get("captured_at") or ""),
        str(record.get("id") or ""),
    )


def _merge_group(records: list[dict[str, Any]]) -> dict[str, Any]:
    primary = sorted(records, key=_score, reverse=True)[0]
    return {
        "scope": str(primary.get("scope") or "project"),
        "kind": str(primary.get("kind") or "workflow"),
        "statement": str(primary.get("statement") or "").strip(),
        "evidence": unique_values(
            item
            for record in records
            for item in (record.get("evidence") or [])
            if str(item or "").strip()
        ),
        "promote_reason": next(
            (str(record.get("promote_reason") or "").strip() for record in records if str(record.get("promote_reason") or "").strip()),
            "",
        ),
        "source_agents": unique_values(str(record.get("source_agent") or "").strip() for record in records),
        "record_ids": [str(record.get("id") or "").strip() for record in records],
        "record_paths": [str(record.get("_path") or "").strip() for record in records],
    }


def _update_record_status(records: list[dict[str, Any]], *, status: str, extra: dict[str, Any]) -> None:
    ts = now_iso()
    for record in records:
        path = Path(str(record.get("_path") or "")).expanduser().resolve()
        payload = load_json_dict(path)
        if not payload:
            continue
        payload["status"] = status
        payload["updated_at"] = ts
        payload.update(extra)
        write_json_dict(path, payload)


def main() -> None:
    parser = argparse.ArgumentParser(description="Curate staged durable-memory proposals into project/global memory.")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--work-item-id", default="", help="Only consider proposals for a specific WI")
    parser.add_argument("--agent-id", default="", help="Only consider proposals for a specific agent run")
    parser.add_argument("--write", action="store_true", help="Promote curated memory proposals")
    parser.add_argument("--allow-global", action="store_true", help="Allow promotion into ~/.codex/memories/global.md")
    parser.add_argument("--memory-file", default="", help="Override project memory target path")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    records = iter_staged_records(
        memory_proposals_dir(project_root),
        schema=MEMORY_PROPOSAL_SCHEMA,
        work_item_id=args.work_item_id,
        status="proposed",
        agent_id=args.agent_id,
    )

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        fp = memory_group_fingerprint(record)
        if fp:
            groups[fp].append(record)

    project_target = Path(args.memory_file).expanduser().resolve() if args.memory_file.strip() else project_memory_path(project_root)
    summary_items: list[dict[str, Any]] = []
    promotions_by_target: dict[Path, list[dict[str, Any]]] = defaultdict(list)
    already_present_count = 0
    blocked_global_count = 0

    for _, group_records in sorted(groups.items()):
        merged = _merge_group(group_records)
        scope = str(merged.get("scope") or "project").strip().lower()
        target = global_memory_path() if scope == "global" else project_target
        target_text = target.read_text(encoding="utf-8", errors="ignore") if target.exists() else ""
        if scope == "global" and not args.allow_global:
            blocked_global_count += 1
            summary_items.append(
                {
                    "action": "blocked_global",
                    "scope": scope,
                    "kind": merged["kind"],
                    "statement": merged["statement"],
                    "target_file": str(target),
                    "record_count": len(group_records),
                }
            )
            continue
        if memory_contains_statement(target_text, merged["statement"]):
            already_present_count += 1
            summary_items.append(
                {
                    "action": "already_present",
                    "scope": scope,
                    "kind": merged["kind"],
                    "statement": merged["statement"],
                    "target_file": str(target),
                    "record_count": len(group_records),
                }
            )
            if args.write:
                _update_record_status(group_records, status="skipped", extra={"skip_reason": "already_present", "memory_file": str(target)})
            continue

        summary_items.append(
            {
                "action": "promote",
                "scope": scope,
                "kind": merged["kind"],
                "statement": merged["statement"],
                "target_file": str(target),
                "record_count": len(group_records),
            }
        )
        promotions_by_target[target].append(merged)

    promoted_count = 0
    if args.write:
        for target, merged_records in promotions_by_target.items():
            promoted = append_memory_entries(target, project_root=project_root, entries=merged_records)
            promoted_statements = {str(entry.get("statement") or "").strip() for entry in promoted}
            promoted_count += len(promoted)
            for merged in merged_records:
                matching = [record for record in records if str(record.get("id") or "") in set(merged["record_ids"])]
                if str(merged.get("statement") or "").strip() in promoted_statements:
                    _update_record_status(
                        matching,
                        status="promoted",
                        extra={
                            "promoted_at": now_iso(),
                            "memory_file": str(target),
                            "promoted_statement": merged["statement"],
                        },
                    )
                else:
                    _update_record_status(
                        matching,
                        status="skipped",
                        extra={"skip_reason": "already_present", "memory_file": str(target)},
                    )

    payload = {
        "schema": MEMORY_CURATION_SCHEMA,
        "generated_at": now_iso(),
        "project": str(project_root),
        "work_item_id": str(args.work_item_id or "").strip(),
        "agent_id": str(args.agent_id or "").strip(),
        "write": bool(args.write),
        "candidate_count": len(records),
        "group_count": len(groups),
        "promotable_count": sum(1 for item in summary_items if item["action"] == "promote"),
        "promoted_count": int(promoted_count),
        "already_present_count": int(already_present_count),
        "blocked_global_count": int(blocked_global_count),
        "items": summary_items,
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
