#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from twlib import list_job_dirs, list_workstream_dirs, now_iso, read_md, resolve_project_root, today_iso_date


DEFAULT_COLUMNS = [
    "id",
    "work_item_id",
    "workstream_id",
    "workstream_title",
    "wave_id",
    "task",
    "status",
    "priority",
    "due_date",
    "estimate_hours",
    "depends_on",
    "started_at",
    "completed_at",
    "blocked_reason",
    "rework_count",
    "rework_reason",
    "reward_target",
    "reward_last_score",
    "reward_last_next_action",
    "notes",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build/update a TheWorkshop task tracker CSV (1 row per job).")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--out", help="Output CSV path (default: outputs/YYYY-MM-DD-task-tracker.csv)")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    out_dir = project_root / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out).expanduser().resolve() if args.out else out_dir / f"{today_iso_date()}-task-tracker.csv"

    rows = []
    for ws_dir in list_workstream_dirs(project_root):
        ws_doc = read_md(ws_dir / "plan.md")
        ws_id = str(ws_doc.frontmatter.get("id") or "").strip()
        ws_title = str(ws_doc.frontmatter.get("title") or "").strip()

        for job_dir in list_job_dirs(ws_dir):
            job_doc = read_md(job_dir / "plan.md")
            fm = job_doc.frontmatter
            wi = str(fm.get("work_item_id") or "").strip()
            title = str(fm.get("title") or "").strip()
            status = str(fm.get("status") or "planned").strip()
            wave_id = str(fm.get("wave_id") or "").strip()
            priority = str(fm.get("priority") or "").strip()
            due_date = str(fm.get("due_date") or "").strip()
            estimate = str(fm.get("estimate_hours") or "").strip()
            depends = fm.get("depends_on", []) or []
            if isinstance(depends, str):
                depends = [d.strip() for d in depends.split(",") if d.strip()]
            depends_text = ", ".join([str(d).strip() for d in depends if str(d).strip()])

            started_at = str(fm.get("started_at") or "").strip()
            completed_at = str(fm.get("completed_at") or "").strip()
            rework_count = str(fm.get("rework_count") or "0").strip()
            rework_reason = str(fm.get("rework_reason") or "").strip()
            reward_target = str(fm.get("reward_target") or "").strip()
            reward_last_score = str(fm.get("reward_last_score") or "").strip()
            reward_last_next_action = str(fm.get("reward_last_next_action") or "").strip()

            rows.append(
                {
                    "id": wi,
                    "work_item_id": wi,
                    "workstream_id": ws_id,
                    "workstream_title": ws_title,
                    "wave_id": wave_id,
                    "task": title,
                    "status": status,
                    "priority": priority,
                    "due_date": due_date,
                    "estimate_hours": estimate,
                    "depends_on": depends_text,
                    "started_at": started_at,
                    "completed_at": completed_at,
                    "blocked_reason": "",
                    "rework_count": rework_count,
                    "rework_reason": rework_reason,
                    "reward_target": reward_target,
                    "reward_last_score": reward_last_score,
                    "reward_last_next_action": reward_last_next_action,
                    "notes": "",
                }
            )

    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=DEFAULT_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    print(str(out_path))


if __name__ == "__main__":
    main()

