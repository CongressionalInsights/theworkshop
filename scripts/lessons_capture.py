#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from twlib import codex_home, ensure_dir, next_id, now_iso, read_md, resolve_project_root, today_yyyymmdd


LESSON_ID_RE = re.compile(r"^##\s+(LL-[0-9]{8}-[0-9]{3})\b")


def existing_lesson_ids(text: str, date: str) -> list[str]:
    out = []
    for ln in text.splitlines():
        m = LESSON_ID_RE.match(ln.strip())
        if not m:
            continue
        lid = m.group(1)
        if lid.startswith(f"LL-{date}-"):
            out.append(lid)
    return out


def rebuild_index(lessons_md: Path, index_path: Path) -> None:
    if not lessons_md.exists():
        index_path.write_text(json.dumps({"schema": "theworkshop.lessons.v1", "lessons": []}, indent=2) + "\n")
        return
    text = lessons_md.read_text(encoding="utf-8", errors="ignore")
    blocks = text.split("\n## ")
    lessons = []
    for i, blk in enumerate(blocks):
        if i == 0:
            continue
        blk = "## " + blk
        header = blk.splitlines()[0].strip()
        m = LESSON_ID_RE.match(header)
        if not m:
            continue
        lid = m.group(1)
        tags = []
        linked = []
        for ln in blk.splitlines()[1:20]:
            if ln.lower().startswith("- applies to:"):
                tags = [t.strip() for t in ln.split(":", 1)[1].split(",") if t.strip()]
            if ln.lower().startswith("- linked:"):
                linked = [t.strip() for t in ln.split(":", 1)[1].split(",") if t.strip()]
        snippet = " ".join(" ".join(blk.splitlines()[0:12]).split())
        lessons.append({"id": lid, "tags": tags, "linked": linked, "snippet": snippet})
    payload = {"schema": "theworkshop.lessons.v1", "generated_at": now_iso(), "lessons": lessons}
    index_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Append a lesson learned and rebuild index.")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--tags", default="", help="Comma-separated tags (e.g., planning,verification)")
    parser.add_argument("--linked", default="", help="Comma-separated IDs to link (WI/WS/PJ)")
    parser.add_argument("--context", required=True, help="Context / what happened")
    parser.add_argument("--worked", required=True, help="What worked")
    parser.add_argument("--failed", default="", help="What failed")
    parser.add_argument("--recommendation", required=True, help="What to do next time")
    parser.add_argument("--also-global", action="store_true", help="Also append to global library (opt-in)")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    notes_dir = project_root / "notes"
    ensure_dir(notes_dir)

    lessons_md = notes_dir / "lessons-learned.md"
    if not lessons_md.exists():
        lessons_md.write_text("# Lessons Learned\n\n", encoding="utf-8")
    text = lessons_md.read_text(encoding="utf-8", errors="ignore")

    date = today_yyyymmdd()
    lid = next_id("LL", date, existing_lesson_ids(text, date))
    ts = now_iso()

    tags = [t.strip() for t in args.tags.split(",") if t.strip()]
    linked = [t.strip() for t in args.linked.split(",") if t.strip()]

    block = "\n".join(
        [
            f"## {lid}",
            f"- Applies to: {', '.join(tags)}",
            f"- Linked: {', '.join(linked)}",
            f"- Captured at: {ts}",
            "",
            f"**Context:** {args.context.strip()}",
            "",
            f"**What worked:** {args.worked.strip()}",
            "",
            f"**What failed:** {args.failed.strip()}",
            "",
            f"**Recommendation:** {args.recommendation.strip()}",
            "",
        ]
    )

    lessons_md.write_text(text.rstrip() + "\n\n" + block, encoding="utf-8")

    index_path = notes_dir / "lessons-index.json"
    rebuild_index(lessons_md, index_path)

    if args.also_global:
        global_path = codex_home() / "skills" / "theworkshop" / "state" / "global-lessons.jsonl"
        ensure_dir(global_path.parent)
        entry = {
            "schema": "theworkshop.lessons.v1",
            "id": lid,
            "tags": tags,
            "linked": linked,
            "captured_at": ts,
            "context": args.context.strip(),
            "worked": args.worked.strip(),
            "failed": args.failed.strip(),
            "recommendation": args.recommendation.strip(),
        }
        with global_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")

    print(str(lessons_md))


if __name__ == "__main__":
    main()
