#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

from twlib import codex_home, now_iso, resolve_project_root


def load_project_index(project_root: Path) -> list[dict]:
    index_path = project_root / "notes" / "lessons-index.json"
    if not index_path.exists():
        return []
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
        return payload.get("lessons", []) or []
    except Exception:
        return []


def load_global_index() -> list[dict]:
    path = codex_home() / "skills" / "theworkshop" / "state" / "global-lessons.jsonl"
    if not path.exists():
        return []
    out = []
    for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not ln.strip():
            continue
        try:
            out.append(json.loads(ln))
        except Exception:
            continue
    # Normalize into the same shape as project index.
    normalized = []
    for e in out:
        recommendation = str(e.get("recommendation", "") or "").strip()
        context = str(e.get("context", "") or "").strip()
        worked = str(e.get("worked", "") or "").strip()
        failed = str(e.get("failed", "") or "").strip()
        captured_at = str(e.get("captured_at", "") or "").strip()
        snippet = " ".join([context[:140], recommendation[:140]]).strip()
        if not snippet:
            snippet = " ".join([worked[:80], failed[:80]]).strip()
        normalized.append(
            {
                "id": e.get("id", ""),
                "tags": e.get("tags", []) or [],
                "linked": e.get("linked", []) or [],
                "snippet": snippet,
                "captured_at": captured_at,
                "context": context,
                "worked": worked,
                "failed": failed,
                "recommendation": recommendation,
            }
        )
    return normalized


def _normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str):
        return [x.strip() for x in value.split(",") if x.strip()]
    return [str(value).strip()] if str(value).strip() else []


def normalize_lesson(lesson: dict[str, Any]) -> dict[str, Any]:
    lid = str(lesson.get("id") or "").strip()
    tags = _normalize_list(lesson.get("tags"))
    linked = _normalize_list(lesson.get("linked"))
    snippet = str(lesson.get("snippet") or "").strip()
    context = str(lesson.get("context") or "").strip()
    worked = str(lesson.get("worked") or "").strip()
    failed = str(lesson.get("failed") or "").strip()
    recommendation = str(lesson.get("recommendation") or "").strip()
    captured_at = str(lesson.get("captured_at") or "").strip()
    if not snippet:
        snippet = " ".join([context, recommendation]).strip()
    if not snippet:
        snippet = " ".join([worked, failed]).strip()
    return {
        "id": lid,
        "tags": tags,
        "linked": linked,
        "snippet": snippet,
        "context": context,
        "worked": worked,
        "failed": failed,
        "recommendation": recommendation,
        "captured_at": captured_at,
    }


def _tokenize(text: str) -> set[str]:
    out: set[str] = set()
    for tok in re.findall(r"[a-z0-9]+", (text or "").lower()):
        if len(tok) >= 3:
            out.add(tok)
    return out


def _parse_lesson_timestamp(lesson: dict[str, Any]) -> dt.datetime | None:
    raw = str(lesson.get("captured_at") or "").strip()
    if raw:
        try:
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            return dt.datetime.fromisoformat(raw)
        except Exception:
            pass

    lid = str(lesson.get("id") or "").strip()
    m = re.match(r"^LL-(\d{8})-\d{3}$", lid)
    if not m:
        return None
    try:
        return dt.datetime.strptime(m.group(1), "%Y%m%d").replace(tzinfo=dt.timezone.utc)
    except Exception:
        return None


def _recency_points(captured_at: dt.datetime | None, now: dt.datetime) -> int:
    if captured_at is None:
        return 0
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=dt.timezone.utc)
    days = max(0, int((now - captured_at).total_seconds() // 86400))
    if days <= 30:
        return 3
    if days <= 180:
        return 2
    if days <= 365:
        return 1
    return 0


def _build_haystack(lesson: dict[str, Any]) -> str:
    parts = [
        str(lesson.get("snippet") or ""),
        str(lesson.get("context") or ""),
        str(lesson.get("worked") or ""),
        str(lesson.get("failed") or ""),
        str(lesson.get("recommendation") or ""),
    ]
    return " ".join(parts).lower().strip()


def score_lesson(
    lesson: dict[str, Any],
    query: str,
    tags: set[str],
    linked_ids: set[str],
    *,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    now_ts = now or dt.datetime.now(dt.timezone.utc)
    norm = normalize_lesson(lesson)
    hay = _build_haystack(norm)
    query_norm = (query or "").lower().strip()
    query_tokens = _tokenize(query_norm)

    text_points = 0
    if not query_norm:
        text_points += 1
    if query_norm and query_norm in hay:
        text_points += 8
    token_hits = 0
    for tok in sorted(query_tokens):
        if tok in hay:
            token_hits += 1
            text_points += 1

    lesson_tags = {t.lower() for t in norm.get("tags", [])}
    tag_overlap = tags.intersection(lesson_tags)
    tag_points = 0
    if tags:
        if tags.issubset(lesson_tags):
            tag_points = 4
        elif tag_overlap:
            tag_points = 2

    lesson_linked = {x.upper() for x in norm.get("linked", [])}
    linked_overlap = linked_ids.intersection(lesson_linked)
    linked_points = min(9, len(linked_overlap) * 3)

    captured_at = _parse_lesson_timestamp(norm)
    recency_points = _recency_points(captured_at, now_ts)

    total = text_points + tag_points + linked_points + recency_points
    return {
        "lesson": norm,
        "score": total,
        "token_hits": token_hits,
        "tag_overlap_count": len(tag_overlap),
        "linked_overlap_count": len(linked_overlap),
        "recency_points": recency_points,
        "captured_at": captured_at,
    }


def rank_lessons(
    lessons: list[dict[str, Any]],
    *,
    query: str = "",
    tags: set[str] | None = None,
    linked_ids: set[str] | None = None,
    now: dt.datetime | None = None,
) -> list[dict[str, Any]]:
    tags_norm = {t.lower() for t in (tags or set()) if t.strip()}
    linked_norm = {x.upper() for x in (linked_ids or set()) if x.strip()}
    scored = [score_lesson(item, query, tags_norm, linked_norm, now=now) for item in lessons]
    scored.sort(
        key=lambda item: (
            -int(item.get("score") or 0),
            -int(item.get("linked_overlap_count") or 0),
            -int(item.get("tag_overlap_count") or 0),
            -int(item.get("token_hits") or 0),
            -(int(item["captured_at"].timestamp()) if item.get("captured_at") else -1),
            str((item.get("lesson") or {}).get("id") or ""),
        )
    )
    return scored


def main() -> None:
    parser = argparse.ArgumentParser(description="Query lessons learned (project-local, optional global).")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--query", default="", help="Search text")
    parser.add_argument("--tags", default="", help="Comma-separated tags to filter")
    parser.add_argument("--linked", default="", help="Comma-separated WI/WS/PJ IDs to prioritize")
    parser.add_argument("--limit", type=int, default=5, help="Max results")
    parser.add_argument("--include-global", action="store_true", help="Include global lessons library if present")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    tags = set([t.strip().lower() for t in args.tags.split(",") if t.strip()])
    linked_ids = set([x.strip().upper() for x in args.linked.split(",") if x.strip()])

    lessons = load_project_index(project_root)
    if args.include_global:
        lessons.extend(load_global_index())

    ranked = rank_lessons(lessons, query=args.query, tags=tags, linked_ids=linked_ids)
    top = ranked[: max(0, int(args.limit))]

    lines = []
    lines.append("# Lessons Query")
    lines.append("")
    lines.append(f"- Generated: {now_iso()}")
    lines.append(f"- Query: {args.query!r}")
    lines.append(f"- Tags: {', '.join(sorted(tags))}")
    lines.append(f"- Linked: {', '.join(sorted(linked_ids))}")
    lines.append("")
    for item in top:
        lesson = item.get("lesson") or {}
        lid = str(lesson.get("id") or "").strip()
        ltags = ", ".join(lesson.get("tags", []) or [])
        score = int(item.get("score") or 0)
        lines.append(f"- **{lid}** ({ltags}) [score={score}]")
        snippet = str(lesson.get("snippet") or "").strip()
        if snippet:
            lines.append(f"  - {snippet}")
    if not top:
        lines.append("- (none)")

    print("\n".join(lines))


if __name__ == "__main__":
    main()
