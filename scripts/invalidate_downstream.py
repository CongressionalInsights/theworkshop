#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from plan_sync import sync_project_plans
from twlib import list_job_dirs, list_workstream_dirs, normalize_str_list, now_iso, read_md, resolve_project_root, write_md


@dataclass
class JobRecord:
    work_item_id: str
    status: str
    depends_on: list[str]
    job_dir: Path
    plan_path: Path


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


def mtime_iso(ts: float | None) -> str:
    if ts is None:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def scan_jobs(project_root: Path) -> dict[str, JobRecord]:
    out: dict[str, JobRecord] = {}
    for ws_dir in list_workstream_dirs(project_root):
        for job_dir in list_job_dirs(ws_dir):
            plan_path = job_dir / "plan.md"
            doc = read_md(plan_path)
            fm = doc.frontmatter
            wi = str(fm.get("work_item_id") or "").strip()
            if not wi:
                continue
            if wi in out:
                continue
            out[wi] = JobRecord(
                work_item_id=wi,
                status=str(fm.get("status") or "planned").strip(),
                depends_on=normalize_str_list(fm.get("depends_on")),
                job_dir=job_dir,
                plan_path=plan_path,
            )
    return out


def build_reverse_deps(jobs: dict[str, JobRecord]) -> dict[str, list[str]]:
    rev: dict[str, list[str]] = defaultdict(list)
    for wi in sorted(jobs.keys()):
        for dep in jobs[wi].depends_on:
            dep_id = dep.strip()
            if not dep_id:
                continue
            rev[dep_id].append(wi)
    for dep_id in list(rev.keys()):
        rev[dep_id] = sorted(set(rev[dep_id]))
    return rev


def downstream_closure(start_wi: str, reverse_deps: dict[str, list[str]]) -> list[str]:
    seen = {start_wi}
    out: set[str] = set()
    q: deque[str] = deque([start_wi])
    while q:
        cur = q.popleft()
        for nxt in reverse_deps.get(cur, []):
            if nxt in seen:
                continue
            seen.add(nxt)
            out.add(nxt)
            q.append(nxt)
    return sorted(out)


def make_current_input_entries(project_root: Path, jobs: dict[str, JobRecord], wi: str) -> list[dict[str, Any]]:
    rec = jobs[wi]
    entries: list[dict[str, Any]] = []
    for dep_id in sorted(set(rec.depends_on)):
        dep = jobs.get(dep_id)
        if dep is None:
            continue

        dep_doc = read_md(dep.plan_path)
        dep_outputs = normalize_str_list(dep_doc.frontmatter.get("outputs"))
        for output_rel in dep_outputs:
            output_path = dep.job_dir / output_rel
            try:
                display_path = str(output_path.relative_to(project_root))
            except Exception:
                display_path = str(output_path)
            exists = output_path.exists() and output_path.is_file()
            mtime: float | None = None
            size_bytes: int | None = None
            file_hash = ""
            if exists:
                st = output_path.stat()
                mtime = float(st.st_mtime)
                size_bytes = int(st.st_size)
                file_hash = sha256_file(output_path)
            entries.append(
                {
                    "dependency_work_item_id": dep_id,
                    "declared_output": output_rel,
                    "exists": exists,
                    "sha256": file_hash,
                    "mtime": mtime,
                    "mtime_iso": mtime_iso(mtime),
                    "size_bytes": size_bytes,
                    "output_path": display_path,
                }
            )
    entries.sort(key=lambda x: (str(x.get("dependency_work_item_id") or ""), str(x.get("declared_output") or "")))
    return entries


def normalize_snapshot_entries(snapshot: Any, *, base_dir: Path | None = None) -> list[dict[str, Any]]:
    if snapshot is None:
        return []

    # Allow a stored path in frontmatter.
    if isinstance(snapshot, str):
        path_text = snapshot.strip()
        if not path_text:
            return []
        p = Path(path_text).expanduser()
        if not p.is_absolute() and base_dir is not None:
            p = (base_dir / p).resolve()
        if not p.exists():
            return []
        try:
            snapshot = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return []

    entries: list[dict[str, Any]] = []
    if isinstance(snapshot, dict):
        if isinstance(snapshot.get("dependencies"), list):
            for dep in snapshot["dependencies"]:
                dep_id = str((dep or {}).get("work_item_id") or (dep or {}).get("dependency_work_item_id") or "").strip()
                outputs = (dep or {}).get("outputs")
                if not isinstance(outputs, list):
                    continue
                for output in outputs:
                    if not isinstance(output, dict):
                        continue
                    entries.append(
                        {
                            "dependency_work_item_id": dep_id or str(output.get("dependency_work_item_id") or "").strip(),
                            "declared_output": str(output.get("declared_output") or output.get("output") or "").strip(),
                            "exists": bool(output.get("exists")),
                            "sha256": str(output.get("sha256") or "").strip(),
                            "mtime": output.get("mtime"),
                            "size_bytes": output.get("size_bytes"),
                        }
                    )
        elif isinstance(snapshot.get("inputs"), list):
            for item in snapshot["inputs"]:
                if not isinstance(item, dict):
                    continue
                entries.append(
                    {
                        "dependency_work_item_id": str(item.get("dependency_work_item_id") or "").strip(),
                        "declared_output": str(item.get("declared_output") or "").strip(),
                        "exists": bool(item.get("exists")),
                        "sha256": str(item.get("sha256") or "").strip(),
                        "mtime": item.get("mtime"),
                        "size_bytes": item.get("size_bytes"),
                    }
                )
        elif isinstance(snapshot.get("entries"), list):
            for item in snapshot["entries"]:
                if not isinstance(item, dict):
                    continue
                entries.append(
                    {
                        "dependency_work_item_id": str(item.get("dependency_work_item_id") or "").strip(),
                        "declared_output": str(item.get("declared_output") or "").strip(),
                        "exists": bool(item.get("exists")),
                        "sha256": str(item.get("sha256") or "").strip(),
                        "mtime": item.get("mtime"),
                        "size_bytes": item.get("size_bytes"),
                    }
                )
    elif isinstance(snapshot, list):
        for item in snapshot:
            if not isinstance(item, dict):
                continue
            entries.append(
                {
                    "dependency_work_item_id": str(item.get("dependency_work_item_id") or "").strip(),
                    "declared_output": str(item.get("declared_output") or "").strip(),
                    "exists": bool(item.get("exists")),
                    "sha256": str(item.get("sha256") or "").strip(),
                    "mtime": item.get("mtime"),
                    "size_bytes": item.get("size_bytes"),
                }
            )

    entries = [e for e in entries if str(e.get("dependency_work_item_id") or "").strip()]
    entries.sort(key=lambda x: (str(x.get("dependency_work_item_id") or ""), str(x.get("declared_output") or "")))
    return entries


def normalize_mtime(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 6)
    except Exception:
        return None


def canonicalize(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in entries:
        dep_id = str(item.get("dependency_work_item_id") or "").strip()
        output_rel = str(item.get("declared_output") or "").strip()
        key = f"{dep_id}::{output_rel}"
        out[key] = {
            "exists": bool(item.get("exists")),
            "sha256": str(item.get("sha256") or "").strip(),
            "mtime": normalize_mtime(item.get("mtime")),
            "size_bytes": int(item.get("size_bytes") or 0) if item.get("size_bytes") is not None else None,
        }
    return out


def compare_snapshot(current_entries: list[dict[str, Any]], truth_snapshot_value: Any, *, base_dir: Path | None = None) -> tuple[bool, str]:
    stored_entries = normalize_snapshot_entries(truth_snapshot_value, base_dir=base_dir)
    if not stored_entries and not current_entries:
        return True, ""
    if not stored_entries:
        return False, "truth_input_snapshot has no comparable entries"

    current_map = canonicalize(current_entries)
    stored_map = canonicalize(stored_entries)

    current_keys = sorted(current_map.keys())
    stored_keys = sorted(stored_map.keys())
    if current_keys != stored_keys:
        only_current = sorted(set(current_keys) - set(stored_keys))
        only_stored = sorted(set(stored_keys) - set(current_keys))
        parts: list[str] = []
        if only_current:
            parts.append(f"new inputs: {', '.join(only_current[:3])}")
        if only_stored:
            parts.append(f"removed inputs: {', '.join(only_stored[:3])}")
        return False, "; ".join(parts) if parts else "input key set changed"

    for key in current_keys:
        current_entry = current_map[key]
        stored_entry = stored_map[key]
        if current_entry.get("exists") != stored_entry.get("exists"):
            return False, f"{key} exists changed ({stored_entry.get('exists')} -> {current_entry.get('exists')})"
        if current_entry.get("sha256") != stored_entry.get("sha256"):
            return False, f"{key} hash changed"
        if current_entry.get("mtime") != stored_entry.get("mtime"):
            return False, f"{key} mtime changed"

    return True, ""


def run_py_best_effort(script: str, project_root: Path) -> None:
    scripts_dir = Path(__file__).resolve().parent
    try:
        proc = subprocess.run(
            [sys.executable, str(scripts_dir / script), "--project", str(project_root)],
            text=True,
            capture_output=True,
            check=False,
        )
    except Exception as exc:
        print(f"warning: {script} failed (best-effort): {exc}", file=sys.stderr)
        return
    if proc.returncode != 0:
        print(f"warning: {script} failed (best-effort)", file=sys.stderr)
        if proc.stderr:
            print(proc.stderr, end="", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="Invalidate stale downstream done jobs when truth input snapshots no longer match dependency outputs.")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--work-item-id", help="Re-scan done downstream jobs of this WI-...")
    scope.add_argument("--upstream-work-item-id", help="Alias for --work-item-id")
    scope.add_argument("--all-scan", action="store_true", help="Scan all jobs with status=done")
    parser.add_argument("--out", help="Output JSON path (default: outputs/invalidation-report.json)")
    parser.add_argument("--no-sync", action="store_true", help="Skip plan/table sync after invalidation")
    parser.add_argument("--no-dashboard", action="store_true", help="Skip dashboard rebuild after invalidation")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    out_dir = project_root / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out).expanduser().resolve() if args.out else out_dir / "invalidation-report.json"

    jobs = scan_jobs(project_root)
    reverse_deps = build_reverse_deps(jobs)

    if args.all_scan:
        scoped_wis = sorted(jobs.keys())
        trigger_wi = ""
    else:
        trigger_wi = str(args.work_item_id or args.upstream_work_item_id or "").strip()
        if trigger_wi not in jobs:
            raise SystemExit(f"Work item not found: {trigger_wi}")
        scoped_wis = downstream_closure(trigger_wi, reverse_deps)

    scanned_done: list[str] = []
    stale_jobs: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []

    for wi in scoped_wis:
        rec = jobs.get(wi)
        if rec is None:
            continue
        doc = read_md(rec.plan_path)
        status = str(doc.frontmatter.get("status") or "planned").strip()
        if status != "done":
            skipped.append({"work_item_id": wi, "reason": f"status={status}"})
            continue

        scanned_done.append(wi)
        current_entries = make_current_input_entries(project_root, jobs, wi)
        truth_snapshot = doc.frontmatter.get("truth_input_snapshot")
        if truth_snapshot in (None, "", [], {}):
            skipped.append({"work_item_id": wi, "reason": "missing truth_input_snapshot"})
            continue

        matches, reason = compare_snapshot(current_entries, truth_snapshot, base_dir=rec.job_dir)
        if matches:
            continue

        ts = now_iso()
        doc.frontmatter["status"] = "blocked"
        doc.frontmatter["completed_at"] = ""
        doc.frontmatter["updated_at"] = ts
        doc.frontmatter["truth_last_status"] = "fail"
        doc.frontmatter["truth_last_checked_at"] = ts
        doc.frontmatter["truth_last_failures"] = [f"freshness_inputs: {reason}"]
        doc.body = append_progress_log(
            doc.body,
            f"{ts} invalidate_downstream: done -> blocked (stale truth_input_snapshot: {reason})",
        )
        write_md(rec.plan_path, doc)

        stale_jobs.append(
            {
                "work_item_id": wi,
                "plan_path": str(rec.plan_path.relative_to(project_root)),
                "reason": reason,
            }
        )

    payload = {
        "schema": "theworkshop.invalidation.v1",
        "generated_at": now_iso(),
        "project": str(project_root),
        "scope": {
            "all_scan": bool(args.all_scan),
            "work_item_id": trigger_wi,
            "scoped_work_items": scoped_wis,
        },
        "counts": {
            "scoped_jobs": len(scoped_wis),
            "scanned_done_jobs": len(scanned_done),
            "stale_jobs": len(stale_jobs),
            "skipped_jobs": len(skipped),
        },
        "stale_jobs": stale_jobs,
        "skipped_jobs": skipped,
    }

    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if stale_jobs and not args.no_sync:
        sync_project_plans(project_root, ts=now_iso())
        run_py_best_effort("task_tracker_build.py", project_root)
    if stale_jobs and not args.no_dashboard:
        run_py_best_effort("orchestrate_plan.py", project_root)
        run_py_best_effort("dashboard_build.py", project_root)

    print(str(out_path))


if __name__ == "__main__":
    main()
