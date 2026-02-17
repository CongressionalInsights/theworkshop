#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from twlib import (
    Job,
    Workstream,
    list_job_dirs,
    list_workstream_dirs,
    load_job,
    normalize_str_list,
    now_iso,
    read_md,
    render_project_workstreams_table,
    render_workstream_jobs_table,
    replace_marker_block,
    resolve_project_root,
    write_md,
    write_workstreams_index,
)


WORKSTREAM_TABLE_START = "<!-- THEWORKSHOP:WORKSTREAM_TABLE_START -->"
WORKSTREAM_TABLE_END = "<!-- THEWORKSHOP:WORKSTREAM_TABLE_END -->"

JOB_TABLE_START = "<!-- THEWORKSHOP:JOB_TABLE_START -->"
JOB_TABLE_END = "<!-- THEWORKSHOP:JOB_TABLE_END -->"


def append_progress_log(body: str, line: str) -> str:
    heading = "# Progress Log"
    if heading not in body:
        return body.rstrip() + "\n\n" + heading + "\n\n" + f"- {line}\n"
    pre, rest = body.split(heading, 1)
    rest_lines = rest.splitlines()
    insert_at = len(rest_lines)
    for i, ln in enumerate(rest_lines[1:], start=1):
        if ln.startswith("# "):
            insert_at = i
            break
    new_rest = rest_lines[:insert_at] + [f"- {line}"] + rest_lines[insert_at:]
    return (pre + heading + "\n" + "\n".join(new_rest)).rstrip() + "\n"


def rollup_status(states: Sequence[str]) -> str:
    if any(s == "in_progress" for s in states):
        return "in_progress"
    if any(s == "blocked" for s in states):
        return "blocked"
    if states and all(s in {"done", "cancelled"} for s in states):
        return "done"
    return "planned"


def workstream_rollup(jobs: list[Job]) -> tuple[str, str]:
    if not jobs:
        return "planned", "no jobs"
    status = rollup_status([j.status for j in jobs])
    details = ", ".join(f"{j.work_item_id}={j.status}" for j in jobs)
    return status, details


def project_rollup(workstreams: list[Workstream]) -> tuple[str, str]:
    if not workstreams:
        return "planned", "no workstreams"
    status = rollup_status([ws.status for ws in workstreams])
    details = ", ".join(f"{ws.id}={ws.status}" for ws in workstreams)
    return status, details


def apply_rollup_transition(frontmatter: dict, body: str, *, prev_status: str, new_status: str, reason: str, ts: str) -> str:
    frontmatter["status"] = new_status

    started_at = str(frontmatter.get("started_at") or "").strip()
    completed_at = str(frontmatter.get("completed_at") or "").strip()

    if new_status in {"in_progress", "blocked"} and not started_at:
        frontmatter["started_at"] = ts
    if new_status == "done":
        if not completed_at:
            frontmatter["completed_at"] = ts
    else:
        # Re-opened scopes should not carry stale completion timestamps.
        frontmatter["completed_at"] = ""

    if prev_status != new_status:
        body = append_progress_log(body, f"{ts} status_rollup: {prev_status} -> {new_status} (because {reason})")
    return body


def merge_order(existing: list[str], computed: list[str]) -> list[str]:
    # Preserve user order for items that still exist; append new ones.
    existing_set = set(existing)
    computed_set = set(computed)
    out = [x for x in existing if x in computed_set]
    for x in computed:
        if x not in existing_set:
            out.append(x)
    return out


@dataclass
class SyncSummary:
    project_updated: bool
    workstreams_updated: int
    updated_paths: list[str]


def sync_project_plans(project_root: Path, *, ts: str | None = None) -> SyncSummary:
    ts = ts or now_iso()
    updated_paths: list[str] = []

    ws_dirs = list_workstream_dirs(project_root)
    workstreams_after: list[Workstream] = []

    # Each workstream: jobs list + Jobs table.
    ws_updated = 0
    for ws_dir in ws_dirs:
        ws_plan = ws_dir / "plan.md"
        ws_doc = read_md(ws_plan)
        jobs = [load_job(p) for p in list_job_dirs(ws_dir)]
        existing_jobs = normalize_str_list(ws_doc.frontmatter.get("jobs"))
        computed_jobs = [j.work_item_id for j in jobs if j.work_item_id]
        ws_doc.frontmatter["jobs"] = merge_order(existing_jobs, computed_jobs)

        prev_status = str(ws_doc.frontmatter.get("status") or "planned").strip()
        new_status, reason = workstream_rollup(jobs)
        ws_doc.body = apply_rollup_transition(
            ws_doc.frontmatter,
            ws_doc.body,
            prev_status=prev_status,
            new_status=new_status,
            reason=reason,
            ts=ts,
        )
        ws_doc.frontmatter["updated_at"] = ts
        job_table = render_workstream_jobs_table(jobs)
        ws_doc.body = replace_marker_block(ws_doc.body, JOB_TABLE_START, JOB_TABLE_END, job_table)
        write_md(ws_plan, ws_doc)

        workstreams_after.append(
            Workstream(
                id=str(ws_doc.frontmatter.get("id") or "").strip(),
                title=str(ws_doc.frontmatter.get("title") or "").strip(),
                status=str(ws_doc.frontmatter.get("status") or "planned").strip(),
                path=ws_dir,
                depends_on=normalize_str_list(ws_doc.frontmatter.get("depends_on")),
            )
        )
        ws_updated += 1
        updated_paths.append(str(ws_plan))

    # Workstreams index: stable navigation.
    write_workstreams_index(project_root, workstreams_after)

    # Project plan: frontmatter workstreams list + rolled-up status + Workstreams table.
    proj_path = project_root / "plan.md"
    proj_doc = read_md(proj_path)
    existing_ws_ids = normalize_str_list(proj_doc.frontmatter.get("workstreams"))
    computed_ws_ids = [ws.id for ws in workstreams_after if ws.id]
    proj_doc.frontmatter["workstreams"] = merge_order(existing_ws_ids, computed_ws_ids)
    prev_proj_status = str(proj_doc.frontmatter.get("status") or "planned").strip()
    new_proj_status, reason = project_rollup(workstreams_after)
    proj_doc.body = apply_rollup_transition(
        proj_doc.frontmatter,
        proj_doc.body,
        prev_status=prev_proj_status,
        new_status=new_proj_status,
        reason=reason,
        ts=ts,
    )
    proj_doc.frontmatter["updated_at"] = ts
    proj_table = render_project_workstreams_table(workstreams_after)
    proj_doc.body = replace_marker_block(proj_doc.body, WORKSTREAM_TABLE_START, WORKSTREAM_TABLE_END, proj_table)
    write_md(proj_path, proj_doc)
    updated_paths.append(str(proj_path))

    return SyncSummary(project_updated=True, workstreams_updated=ws_updated, updated_paths=updated_paths)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync TheWorkshop marker-block tables and indices from on-disk state.")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    summary = sync_project_plans(project_root)

    print(f"{project_root}")
    print(f"- project plan synced: {summary.project_updated}")
    print(f"- workstreams synced: {summary.workstreams_updated}")


if __name__ == "__main__":
    main()
