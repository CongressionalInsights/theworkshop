#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from learning_store import (
    LESSON_CANDIDATE_SCHEMA,
    LESSON_CURATION_SCHEMA,
    iter_staged_records,
    lesson_candidates_dir,
    lesson_group_fingerprint,
    load_json_dict,
    normalize_text,
    unique_values,
    write_json_dict,
)
from lessons_capture import capture_lesson
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
        "context": str(primary.get("context") or "").strip(),
        "worked": str(primary.get("worked") or "").strip(),
        "failed": str(primary.get("failed") or "").strip(),
        "recommendation": str(primary.get("recommendation") or "").strip(),
        "tags": unique_values(item for record in records for item in (record.get("tags") or [])),
        "linked": unique_values(item for record in records for item in (record.get("linked") or [])),
        "source_agents": unique_values(str(record.get("source_agent") or "").strip() for record in records),
        "record_ids": [str(record.get("id") or "").strip() for record in records],
    }


def _existing_lesson_keys(project_root: Path) -> set[str]:
    index_path = project_root / "notes" / "lessons-index.json"
    if not index_path.exists():
        return set()
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    lessons = payload.get("lessons") if isinstance(payload, dict) else None
    if not isinstance(lessons, list):
        return set()
    keys: set[str] = set()
    for lesson in lessons:
        if not isinstance(lesson, dict):
            continue
        key = "|".join(
            [
                normalize_text(lesson.get("recommendation")),
                normalize_text(lesson.get("worked")),
                normalize_text(lesson.get("failed")),
            ]
        )
        if key.strip("|"):
            keys.add(key)
    return keys


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
    parser = argparse.ArgumentParser(description="Curate staged lesson candidates into canonical lessons-learned artifacts.")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--work-item-id", default="", help="Only consider candidates for a specific WI")
    parser.add_argument("--agent-id", default="", help="Only consider candidates for a specific agent run")
    parser.add_argument("--write", action="store_true", help="Promote curated lesson candidates")
    parser.add_argument("--also-global", action="store_true", help="Also append promoted lessons to the global lessons library")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    records = iter_staged_records(
        lesson_candidates_dir(project_root),
        schema=LESSON_CANDIDATE_SCHEMA,
        work_item_id=args.work_item_id,
        status="proposed",
        agent_id=args.agent_id,
    )

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        fp = lesson_group_fingerprint(record)
        if fp:
            groups[fp].append(record)

    existing_keys = _existing_lesson_keys(project_root)
    summary_items: list[dict[str, Any]] = []
    promoted_count = 0
    already_present_count = 0

    for _, group_records in sorted(groups.items()):
        merged = _merge_group(group_records)
        key = "|".join(
            [
                normalize_text(merged.get("recommendation")),
                normalize_text(merged.get("worked")),
                normalize_text(merged.get("failed")),
            ]
        )
        matching = [record for record in records if str(record.get("id") or "") in set(merged["record_ids"])]
        if key in existing_keys and key.strip("|"):
            already_present_count += 1
            summary_items.append(
                {
                    "action": "already_present",
                    "recommendation": merged["recommendation"],
                    "record_count": len(group_records),
                }
            )
            if args.write:
                _update_record_status(matching, status="skipped", extra={"skip_reason": "already_present"})
            continue

        item: dict[str, Any] = {
            "action": "promote",
            "recommendation": merged["recommendation"],
            "record_count": len(group_records),
        }
        if args.write:
            result = capture_lesson(
                project_root,
                tags=list(merged["tags"]),
                linked=list(merged["linked"]),
                context=merged["context"],
                worked=merged["worked"],
                failed=merged["failed"],
                recommendation=merged["recommendation"],
                also_global=bool(args.also_global),
            )
            promoted_count += 1
            item["lesson_id"] = result["lesson_id"]
            existing_keys.add(key)
            _update_record_status(
                matching,
                status="promoted",
                extra={"promoted_at": now_iso(), "lesson_id": result["lesson_id"]},
            )
        summary_items.append(item)

    payload = {
        "schema": LESSON_CURATION_SCHEMA,
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
        "items": summary_items,
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
