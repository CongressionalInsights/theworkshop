#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from tw_tools import (
    append_section_bullet,
    find_job_dir,
    find_workstream_dir,
    infer_context_ref,
    merge_unique,
    parse_markdown_safe,
    rel_project_path,
)
from twlib import now_iso, read_md, resolve_project_root, write_md
from twyaml import MarkdownDoc


def _today_yyyymmdd() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _prompt_lines(prompt: str) -> list[str]:
    print(prompt)
    print("Enter one item per line. Submit an empty line to finish.")
    out: list[str] = []
    while True:
        try:
            value = input("> ").strip()
        except EOFError:
            break
        if not value:
            break
        out.append(value)
    return out


def _render_context_body(target_kind: str, target_id: str, locked: list[str], deferred: list[str], notes: list[str]) -> str:
    lines: list[str] = []
    lines.append("# Context")
    lines.append("")
    lines.append(f"- Target: `{target_kind}` `{target_id}`")
    lines.append("")
    lines.append("## Locked Decisions")
    lines.append("")
    if locked:
        for item in locked:
            lines.append(f"- {item}")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Deferred Ideas")
    lines.append("")
    if deferred:
        for item in deferred:
            lines.append(f"- {item}")
    else:
        lines.append("- (none)")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    if notes:
        for item in notes:
            lines.append(f"- {item}")
    else:
        lines.append("- (none)")
    lines.append("")
    return "\n".join(lines)


def _load_existing_context(path: Path) -> tuple[list[str], list[str], list[str], str]:
    doc, err = parse_markdown_safe(path)
    if err or doc is None:
        return [], [], [], ""
    fm = doc.frontmatter
    locked = [str(x) for x in (fm.get("locked_decisions") or []) if str(x).strip()]
    deferred = [str(x) for x in (fm.get("deferred_ideas") or []) if str(x).strip()]
    notes = [str(x) for x in (fm.get("notes") or []) if str(x).strip()]
    created_at = str(fm.get("created_at") or "")
    return locked, deferred, notes, created_at


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture TheWorkshop intent context for a workstream or job.")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--work-item-id", help="Job target WI-...")
    parser.add_argument("--workstream-id", help="Workstream target WS-...")
    parser.add_argument("--decision", action="append", default=[], help="Locked decision (repeatable)")
    parser.add_argument("--defer", action="append", default=[], help="Deferred idea (repeatable)")
    parser.add_argument("--note", action="append", default=[], help="Additional note (repeatable)")
    parser.add_argument("--replace", action="store_true", help="Replace existing decisions/deferred/notes instead of merging")
    parser.add_argument("--required", action="store_true", help="For job targets: set context_required=true")
    parser.add_argument("--optional", action="store_true", help="For job targets: set context_required=false")
    parser.add_argument("--no-interactive", action="store_true", help="Do not prompt for missing decisions interactively")
    args = parser.parse_args()

    if bool(args.work_item_id) == bool(args.workstream_id):
        raise SystemExit("Provide exactly one target: --work-item-id or --workstream-id")
    if args.required and args.optional:
        raise SystemExit("--required and --optional are mutually exclusive")

    project_root = resolve_project_root(args.project)
    ts = now_iso()

    target_kind = "job" if args.work_item_id else "workstream"
    target_id = str(args.work_item_id or args.workstream_id).strip()
    if not target_id:
        raise SystemExit("Target id cannot be empty")

    # Validate target and infer context path.
    if target_kind == "job":
        target_dir = find_job_dir(project_root, target_id)
        target_plan = target_dir / "plan.md"
    else:
        target_dir = find_workstream_dir(project_root, target_id)
        target_plan = target_dir / "plan.md"

    context_rel = infer_context_ref(project_root, target_id)
    context_path = project_root / context_rel
    context_path.parent.mkdir(parents=True, exist_ok=True)

    existing_locked, existing_deferred, existing_notes, existing_created_at = _load_existing_context(context_path)

    locked = [x.strip() for x in args.decision if str(x).strip()]
    deferred = [x.strip() for x in args.defer if str(x).strip()]
    notes = [x.strip() for x in args.note if str(x).strip()]

    if not args.no_interactive and not locked and not deferred and not notes:
        locked = _prompt_lines("Locked decisions for this target:")
        deferred = _prompt_lines("Deferred ideas (out of scope for current execution):")
        notes = _prompt_lines("Additional context notes:")

    if args.replace:
        merged_locked = locked
        merged_deferred = deferred
        merged_notes = notes
    else:
        merged_locked = merge_unique(existing_locked, locked)
        merged_deferred = merge_unique(existing_deferred, deferred)
        merged_notes = merge_unique(existing_notes, notes)

    if not merged_locked and not merged_deferred and not merged_notes:
        merged_notes = [f"{_today_yyyymmdd()}: context scaffold created"]

    context_fm = {
        "schema": "theworkshop.context.v1",
        "target_kind": target_kind,
        "target_id": target_id,
        "created_at": existing_created_at or ts,
        "updated_at": ts,
        "locked_decisions": merged_locked,
        "deferred_ideas": merged_deferred,
        "notes": merged_notes,
    }
    context_doc = MarkdownDoc(
        frontmatter=context_fm,
        body=_render_context_body(target_kind, target_id, merged_locked, merged_deferred, merged_notes),
    )
    write_md(context_path, context_doc)

    # Link target plan to context.
    plan_doc = read_md(target_plan)
    plan_doc.frontmatter["context_ref"] = context_rel
    if target_kind == "job":
        if args.required:
            plan_doc.frontmatter["context_required"] = True
        elif args.optional:
            plan_doc.frontmatter["context_required"] = False
        elif "context_required" not in plan_doc.frontmatter:
            plan_doc.frontmatter["context_required"] = False
    plan_doc.frontmatter["updated_at"] = ts
    plan_doc.body = append_section_bullet(plan_doc.body, "# Progress Log", f"{ts} discuss: context captured at `{context_rel}`")
    write_md(target_plan, plan_doc)

    print(rel_project_path(project_root, context_path))


if __name__ == "__main__":
    main()
