#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from twlib import normalize_str_list, now_iso, read_md, resolve_project_root, write_md


def find_job_dir(project_root: Path, wi: str) -> Path:
    matches = list(project_root.glob(f"workstreams/WS-*/jobs/{wi}-*"))
    if len(matches) != 1:
        raise SystemExit(f"Expected exactly 1 job dir for {wi}, got {len(matches)}: {matches}")
    return matches[0]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def mtime_iso(ts: float | None) -> str:
    if ts is None:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def output_fingerprint(project_root: Path, dep_id: str, dep_job_dir: Path, output_rel: str) -> dict[str, object]:
    output_path = dep_job_dir / output_rel
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
    return {
        "dependency_work_item_id": dep_id,
        "declared_output": output_rel,
        "output_path": display_path,
        "exists": exists,
        "sha256": file_hash,
        "mtime": mtime,
        "mtime_iso": mtime_iso(mtime),
        "size_bytes": size_bytes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture dependency-output input snapshot for a TheWorkshop job.")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--work-item-id", required=True, help="WI-... to snapshot inputs for")
    parser.add_argument(
        "--out",
        help="Output JSON path (default: <job>/artifacts/input-snapshot.json)",
    )
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    wi = args.work_item_id.strip()
    job_dir = find_job_dir(project_root, wi)
    plan_doc = read_md(job_dir / "plan.md")

    dependencies = normalize_str_list(plan_doc.frontmatter.get("depends_on"))
    dependency_entries: list[dict[str, object]] = []
    total_outputs = 0

    for dep_id in sorted(set(dependencies)):
        dep_record: dict[str, object] = {
            "work_item_id": dep_id,
            "job_found": False,
            "job_plan_path": "",
            "outputs_declared": [],
            "outputs": [],
        }
        matches = list(project_root.glob(f"workstreams/WS-*/jobs/{dep_id}-*"))
        if len(matches) != 1:
            dependency_entries.append(dep_record)
            continue

        dep_job_dir = matches[0]
        dep_doc = read_md(dep_job_dir / "plan.md")
        outputs_declared = normalize_str_list(dep_doc.frontmatter.get("outputs"))
        output_entries = [
            output_fingerprint(project_root, dep_id, dep_job_dir, output_rel)
            for output_rel in outputs_declared
        ]

        dep_record["job_found"] = True
        dep_record["job_plan_path"] = str((dep_job_dir / "plan.md").relative_to(project_root))
        dep_record["outputs_declared"] = outputs_declared
        dep_record["outputs"] = output_entries

        total_outputs += len(output_entries)
        dependency_entries.append(dep_record)

    payload = {
        "schema": "theworkshop.inputsnapshot.v1",
        "generated_at": now_iso(),
        "project": str(project_root),
        "work_item_id": wi,
        "dependency_count": len(dependency_entries),
        "input_count": total_outputs,
        "dependencies": dependency_entries,
    }

    default_out = job_dir / "artifacts" / "input-snapshot.json"
    out_path = Path(args.out).expanduser().resolve() if args.out else default_out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    # Keep plan frontmatter aligned with the actual snapshot path.
    try:
        rel_out = str(out_path.relative_to(job_dir))
    except Exception:
        rel_out = str(out_path)
    plan_doc.frontmatter["truth_input_snapshot"] = rel_out
    plan_doc.frontmatter["updated_at"] = now_iso()
    write_md(job_dir / "plan.md", plan_doc)
    print(str(out_path))


if __name__ == "__main__":
    main()
