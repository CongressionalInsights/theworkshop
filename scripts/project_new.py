#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from twlib import ensure_dir, kebab, next_id, now_iso, today_yyyymmdd
from twyaml import MarkdownDoc
from twlib import write_md


WORKSTREAM_TABLE_START = "<!-- THEWORKSHOP:WORKSTREAM_TABLE_START -->"
WORKSTREAM_TABLE_END = "<!-- THEWORKSHOP:WORKSTREAM_TABLE_END -->"


def default_base_dir() -> Path:
    return Path.home() / "codex" / "projects" / "theworkshop"


def existing_project_ids(base_dir: Path, date: str) -> list[str]:
    if not base_dir.exists():
        return []
    out = []
    for p in base_dir.iterdir():
        if not p.is_dir():
            continue
        name = p.name
        if name.startswith(f"PJ-{date}-"):
            parts = name.split("-", 3)
            if len(parts) >= 3:
                out.append("-".join(parts[:3]))
    return out


def build_project_plan(project_id: str, title: str) -> MarkdownDoc:
    ts = now_iso()
    fm = {
        "schema": "theworkshop.plan.v1",
        "kind": "project",
        "id": project_id,
        "title": title,
        "status": "planned",
        "agreement_status": "proposed",
        "agreed_at": "",
        "agreed_notes": "",
        "started_at": ts,
        "updated_at": ts,
        "completed_at": "",
        "completion_promise": f"{project_id}-DONE",
        "reward_mode": "behavior_driving",
        "github_enabled": False,
        "github_repo": "",
        "subagent_policy": "auto",
        "max_parallel_agents": 3,
        "waves": [],
        "workstreams": [],
    }

    body = "\n".join(
        [
            "# Goal",
            "",
            "_Describe the goal in plain language._",
            "",
            "# Acceptance Criteria",
            "",
            "- _Define what \"done\" means (outputs + checks)._",
            "",
            "# Workstreams",
            "",
            WORKSTREAM_TABLE_START,
            "| Workstream | Status | Title | Depends On |",
            "| --- | --- | --- | --- |",
            "| (none) |  |  |  |",
            WORKSTREAM_TABLE_END,
            "",
            "# Success Hook",
            "",
            "- Acceptance criteria: see above",
            "- Verification: run `scripts/plan_check.py` and confirm required outputs exist",
            f"- Completion promise: `<promise>{project_id}-DONE</promise>`",
            "",
            "# Progress Log",
            "",
            f"- {ts} created project",
            "",
            "# Decisions",
            "",
            f"- {ts}: initialized project structure",
            "",
            "# Lessons Learned (Links)",
            "",
            "- `notes/lessons-learned.md`",
            "",
            "# Compatibility Notes",
            "",
            "- schema: `theworkshop.plan.v1`",
            "",
        ]
    )

    return MarkdownDoc(frontmatter=fm, body=body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a new TheWorkshop project root.")
    parser.add_argument("--name", required=True, help="Project title")
    parser.add_argument("--base-dir", help="Base directory (default: ~/codex/projects/theworkshop)")
    parser.add_argument("--slug", help="Override directory slug (kebab-case)")
    args = parser.parse_args()

    base_dir = Path(args.base_dir).expanduser().resolve() if args.base_dir else default_base_dir()
    ensure_dir(base_dir)

    date = today_yyyymmdd()
    existing = existing_project_ids(base_dir, date)
    project_id = next_id("PJ", date, existing)
    slug = kebab(args.slug) if args.slug else kebab(args.name)
    project_dir = base_dir / f"{project_id}-{slug}"

    ensure_dir(project_dir)
    for d in ["inputs", "outputs", "notes", "logs", "artifacts", "tmp", "tools", "workstreams"]:
        ensure_dir(project_dir / d)

    # Seed required docs
    write_md(project_dir / "plan.md", build_project_plan(project_id, args.name))
    (project_dir / "workstreams" / "index.md").write_text("# Workstreams\n\n- (none)\n", encoding="utf-8")
    (project_dir / "notes" / "lessons-learned.md").write_text("# Lessons Learned\n\n", encoding="utf-8")

    print(str(project_dir))


if __name__ == "__main__":
    main()
