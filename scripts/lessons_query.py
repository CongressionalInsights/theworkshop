#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

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
        normalized.append(
            {
                "id": e.get("id", ""),
                "tags": e.get("tags", []) or [],
                "linked": e.get("linked", []) or [],
                "snippet": " ".join(
                    [
                        str(e.get("context", ""))[:140],
                        str(e.get("recommendation", ""))[:140],
                    ]
                ).strip(),
            }
        )
    return normalized


def score_lesson(lesson: dict, query: str, tags: set[str]) -> int:
    s = 0
    q = query.lower().strip()
    if not q:
        s += 1
    hay = (lesson.get("snippet") or "").lower()
    if q and q in hay:
        s += 5
    for token in q.split():
        if token and token in hay:
            s += 1
    if tags:
        lt = set([t.lower() for t in (lesson.get("tags") or [])])
        if tags.issubset(lt):
            s += 3
        elif tags.intersection(lt):
            s += 1
    return s


def main() -> None:
    parser = argparse.ArgumentParser(description="Query lessons learned (project-local, optional global).")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--query", default="", help="Search text")
    parser.add_argument("--tags", default="", help="Comma-separated tags to filter")
    parser.add_argument("--limit", type=int, default=5, help="Max results")
    parser.add_argument("--include-global", action="store_true", help="Include global lessons library if present")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    tags = set([t.strip().lower() for t in args.tags.split(",") if t.strip()])

    lessons = load_project_index(project_root)
    if args.include_global:
        lessons.extend(load_global_index())

    ranked = sorted(lessons, key=lambda l: score_lesson(l, args.query, tags), reverse=True)
    top = ranked[: max(0, int(args.limit))]

    lines = []
    lines.append("# Lessons Query")
    lines.append("")
    lines.append(f"- Generated: {now_iso()}")
    lines.append(f"- Query: {args.query!r}")
    lines.append(f"- Tags: {', '.join(sorted(tags))}")
    lines.append("")
    for item in top:
        lines.append(f"- **{item.get('id','')}** ({', '.join(item.get('tags', []) or [])})")
        lines.append(f"  - {item.get('snippet','')}")
    if not top:
        lines.append("- (none)")

    print("\n".join(lines))


if __name__ == "__main__":
    main()

