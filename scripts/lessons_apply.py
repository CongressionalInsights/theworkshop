#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from lessons_query import load_global_index, load_project_index, rank_lessons
from tw_tools import extract_section, replace_section
from twlib import now_iso, read_md, resolve_project_root, write_md


LESSON_ID_RE = re.compile(r"\bLL-\d{8}-\d{3}\b")


def looks_placeholder(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return True
    markers = [
        "to be filled",
        "auto-populated at job start",
        "to be filled at job start by lessons retrieval",
        "- (none)",
    ]
    return any(m in t for m in markers)


def find_job_plan(project_root: Path, work_item_id: str) -> Path:
    matches = list(project_root.glob(f"workstreams/WS-*/jobs/{work_item_id}-*/plan.md"))
    if len(matches) != 1:
        raise SystemExit(f"Expected exactly 1 plan.md for {work_item_id}, got {len(matches)}")
    return matches[0]


def _normalize_tags(value: set[str] | list[str] | None) -> set[str]:
    if not value:
        return set()
    out: set[str] = set()
    for item in value:
        s = str(item).strip().lower()
        if s:
            out.add(s)
    return out


def _context_ids(project_root: Path, job_plan: Path, work_item_id: str) -> set[str]:
    out: set[str] = {work_item_id.strip().upper()}
    ws_plan = job_plan.parents[2] / "plan.md"
    if ws_plan.exists():
        ws_doc = read_md(ws_plan)
        ws_id = str(ws_doc.frontmatter.get("id") or "").strip().upper()
        if ws_id:
            out.add(ws_id)
    proj_doc = read_md(project_root / "plan.md")
    pj_id = str(proj_doc.frontmatter.get("id") or "").strip().upper()
    if pj_id:
        out.add(pj_id)
    return out


def _compose_query(job_title: str, objective: str, query_override: str = "") -> str:
    if query_override.strip():
        return query_override.strip()
    return " ".join([job_title.strip(), objective.strip()]).strip()


def _render_lesson_line(item: dict[str, Any]) -> str:
    lesson = item.get("lesson") or {}
    lid = str(lesson.get("id") or "").strip()
    recommendation = str(lesson.get("recommendation") or "").strip()
    snippet = str(lesson.get("snippet") or "").strip()
    summary = recommendation or snippet or "No summary available."
    summary = " ".join(summary.split())

    reasons: list[str] = []
    if int(item.get("linked_overlap_count") or 0) > 0:
        reasons.append("linked ID overlap")
    if int(item.get("tag_overlap_count") or 0) > 0:
        reasons.append("tag overlap")
    if int(item.get("token_hits") or 0) > 0:
        reasons.append("text match")
    if int(item.get("recency_points") or 0) > 0:
        reasons.append("recent")

    reason_text = f" [{', '.join(reasons)}]" if reasons else ""
    return f"- {lid}: {summary}{reason_text}"


def apply_lessons_to_job(
    project_root: Path,
    work_item_id: str,
    *,
    limit: int = 5,
    include_global: bool = False,
    tags: set[str] | list[str] | None = None,
    query_override: str = "",
    dry_run: bool = False,
) -> dict[str, Any]:
    job_plan = find_job_plan(project_root, work_item_id)
    doc = read_md(job_plan)

    title = str(doc.frontmatter.get("title") or "").strip()
    objective = extract_section(doc.body, "# Objective")
    query = _compose_query(title, objective, query_override=query_override)
    linked_ids = _context_ids(project_root, job_plan, work_item_id)
    tags_norm = _normalize_tags(tags)

    lessons = load_project_index(project_root)
    if include_global:
        lessons.extend(load_global_index())

    ranked = rank_lessons(lessons, query=query, tags=tags_norm, linked_ids=linked_ids)
    top = ranked[: max(0, int(limit))]

    generated_lines = [_render_lesson_line(item) for item in top if str((item.get("lesson") or {}).get("id") or "").strip()]
    if not generated_lines:
        generated_lines = ["- No matching lessons found; proceed with explicit verification and reproducible evidence."]

    section_heading = "# Relevant Lessons Learned"
    current = extract_section(doc.body, section_heading)
    current_lines = [ln.rstrip() for ln in current.splitlines() if ln.strip()]
    current_ids = set(LESSON_ID_RE.findall(current))
    generated_ids = set()
    for line in generated_lines:
        generated_ids.update(LESSON_ID_RE.findall(line))

    replaced = looks_placeholder(current)
    appended = 0
    if replaced:
        next_lines = generated_lines
        appended = len(generated_lines)
    else:
        appendable = [ln for ln in generated_lines if not set(LESSON_ID_RE.findall(ln)).intersection(current_ids)]
        if not appendable:
            return {
                "work_item_id": work_item_id,
                "plan_path": str(job_plan),
                "replaced": False,
                "appended": 0,
                "applied_ids": sorted(generated_ids),
                "status": "no_change",
            }
        appended = len(appendable)
        stamp = now_iso()
        next_lines = current_lines + [f"- Auto-applied lessons at {stamp}:"] + appendable

    if not dry_run:
        doc.body = replace_section(doc.body, section_heading, next_lines)
        doc.frontmatter["updated_at"] = now_iso()
        write_md(job_plan, doc)

    return {
        "work_item_id": work_item_id,
        "plan_path": str(job_plan),
        "replaced": replaced,
        "appended": appended,
        "applied_ids": sorted(generated_ids),
        "status": "updated" if appended > 0 else "no_change",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply relevant lessons into a job's # Relevant Lessons Learned section.")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--work-item-id", required=True, help="WI-... target job")
    parser.add_argument("--limit", type=int, default=5, help="Max lessons to apply")
    parser.add_argument("--include-global", action="store_true", help="Include global lessons library when present")
    parser.add_argument("--tags", default="", help="Optional comma-separated tags")
    parser.add_argument("--query", default="", help="Override auto-generated query text")
    parser.add_argument("--dry-run", action="store_true", help="Print what would change without writing the plan")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    tags = {t.strip().lower() for t in args.tags.split(",") if t.strip()}

    result = apply_lessons_to_job(
        project_root,
        args.work_item_id.strip(),
        limit=args.limit,
        include_global=bool(args.include_global),
        tags=tags,
        query_override=args.query,
        dry_run=bool(args.dry_run),
    )
    print(
        f"{result['plan_path']} "
        f"(status={result['status']}, replaced={result['replaced']}, appended={result['appended']}, "
        f"applied={','.join(result['applied_ids'])})"
    )


if __name__ == "__main__":
    main()
