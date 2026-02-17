#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from twlib import (
    Workstream,
    ensure_dir,
    kebab,
    list_workstream_dirs,
    load_workstream,
    normalize_str_list,
    next_id,
    now_iso,
    render_project_workstreams_table,
    replace_marker_block,
    resolve_project_root,
    scan_project,
    set_frontmatter_field,
    today_yyyymmdd,
    write_md,
    write_workstreams_index,
)
from twyaml import MarkdownDoc


WORKSTREAM_TABLE_START = "<!-- THEWORKSHOP:WORKSTREAM_TABLE_START -->"
WORKSTREAM_TABLE_END = "<!-- THEWORKSHOP:WORKSTREAM_TABLE_END -->"

JOB_TABLE_START = "<!-- THEWORKSHOP:JOB_TABLE_START -->"
JOB_TABLE_END = "<!-- THEWORKSHOP:JOB_TABLE_END -->"


def existing_ws_ids(project_root: Path, date: str) -> list[str]:
    out: list[str] = []
    for p in list_workstream_dirs(project_root):
        name = p.name
        if name.startswith(f"WS-{date}-"):
            parts = name.split("-", 3)
            if len(parts) >= 3:
                out.append("-".join(parts[:3]))
    return out


def build_workstream_plan(ws_id: str, title: str, depends_on: list[str]) -> MarkdownDoc:
    ts = now_iso()
    fm = {
        "schema": "theworkshop.plan.v1",
        "kind": "workstream",
        "id": ws_id,
        "title": title,
        "status": "planned",
        "depends_on": depends_on,
        "started_at": "",
        "updated_at": ts,
        "completed_at": "",
        "completion_promise": f"{ws_id}-DONE",
        "jobs": [],
    }
    body = "\n".join(
        [
            "# Purpose (How This Supports The Project Goal)",
            "",
            "_Explain how this workstream supports the project goal._",
            "",
            "# Jobs",
            "",
            JOB_TABLE_START,
            "| Work Item | Status | Title | Wave | Depends On | Reward | Next Action |",
            "| --- | --- | --- | --- | --- | --- | --- |",
            "| (none) |  |  |  |  |  |  |",
            JOB_TABLE_END,
            "",
            "# Dependencies",
            "",
            "_Workstream-level dependencies._",
            "",
            "# Success Hook",
            "",
            "- Acceptance criteria: all jobs done and workstream summary exists",
            "- Verification: run `scripts/plan_check.py`",
            f"- Completion promise: `<promise>{ws_id}-DONE</promise>`",
            "",
            "# Progress Log",
            "",
            f"- {ts} created workstream",
            "",
            "# Lessons Learned (Links)",
            "",
            "- `notes/lessons-learned.md` (project)",
            "",
        ]
    )
    return MarkdownDoc(frontmatter=fm, body=body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Add a TheWorkshop workstream to an existing project.")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--title", required=True, help="Workstream title")
    parser.add_argument("--slug", help="Optional slug override")
    parser.add_argument("--depends-on", action="append", default=[], help="Workstream dependency WS-... (repeatable)")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    ts = now_iso()

    date = today_yyyymmdd()
    ws_id = next_id("WS", date, existing_ws_ids(project_root, date))
    slug = kebab(args.slug) if args.slug else kebab(args.title)
    ws_dir = project_root / "workstreams" / f"{ws_id}-{slug}"

    ensure_dir(ws_dir)
    ensure_dir(ws_dir / "jobs")
    ensure_dir(ws_dir / "notes")
    ensure_dir(ws_dir / "outputs")
    ensure_dir(ws_dir / "logs")
    ensure_dir(ws_dir / "artifacts")

    write_md(ws_dir / "plan.md", build_workstream_plan(ws_id, args.title, args.depends_on))

    # Update project plan: frontmatter + workstreams table
    proj_doc, workstreams, _jobs = scan_project(project_root)
    ws_ids = normalize_str_list(proj_doc.frontmatter.get("workstreams"))
    if ws_id not in ws_ids:
        ws_ids.append(ws_id)
    set_frontmatter_field(proj_doc, "workstreams", ws_ids)
    set_frontmatter_field(proj_doc, "updated_at", ts)

    # Re-scan workstreams including the one we just created
    workstreams = [load_workstream(p) for p in list_workstream_dirs(project_root)]
    table = render_project_workstreams_table(workstreams)
    proj_doc.body = replace_marker_block(proj_doc.body, WORKSTREAM_TABLE_START, WORKSTREAM_TABLE_END, table)
    write_md(project_root / "plan.md", proj_doc)

    write_workstreams_index(project_root, workstreams)
    print(ws_id)


if __name__ == "__main__":
    main()
