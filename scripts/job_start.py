#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from lessons_apply import apply_lessons_to_job
from transition import transition_entity
from tw_tools import append_section_bullet, validate_context_gate_for_job
from twlib import normalize_str_list, now_iso, read_md, resolve_project_root, write_md


def append_decision_log(body: str, line: str) -> str:
    heading = "# Decisions"
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


def find_job_dir(project_root: Path, wi: str) -> Path:
    matches = list(project_root.glob(f"workstreams/WS-*/jobs/{wi}-*"))
    if len(matches) != 1:
        raise SystemExit(f"Expected exactly 1 job dir for {wi}, got {len(matches)}: {matches}")
    return matches[0]


def parent_workstream_dir(project_root: Path, job_dir: Path) -> Path:
    try:
        rel = job_dir.relative_to(project_root)
    except Exception:
        raise SystemExit(f"Job dir is not under project root: {job_dir}")
    parts = rel.parts
    if len(parts) < 4 or parts[0] != "workstreams" or parts[2] != "jobs":
        raise SystemExit(f"Unexpected job path layout: {rel}")
    ws_dir = project_root / parts[0] / parts[1]
    if not ws_dir.exists():
        raise SystemExit(f"Parent workstream directory not found: {ws_dir}")
    return ws_dir


def dependency_statuses(project_root: Path, wi_ids: list[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for dep in wi_ids:
        matches = list(project_root.glob(f"workstreams/WS-*/jobs/{dep}-*/plan.md"))
        if len(matches) != 1:
            out.append((dep, "missing"))
            continue
        dep_doc = read_md(matches[0])
        dep_status = str(dep_doc.frontmatter.get("status") or "planned").strip()
        out.append((dep, dep_status))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Start a TheWorkshop job (canonical transition + monitor runtime).")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--work-item-id", required=True, help="WI-... to start")
    parser.add_argument("--no-sync", action="store_true", help="Do not run plan_sync after updating the job")
    parser.add_argument("--no-dashboard", action="store_true", help="Skip dashboard projector")
    parser.add_argument("--no-open", action="store_true", help="Do not open dashboard window")
    parser.add_argument("--no-monitor", action="store_true", help="Do not start monitor runtime")
    parser.add_argument("--no-apply-lessons", action="store_true", help="Skip automatic lessons application at job start")
    parser.add_argument("--lessons-limit", type=int, default=5, help="Max lessons to apply when job starts")
    parser.add_argument(
        "--lessons-include-global",
        action="store_true",
        help="Include global lessons library in automatic lessons application",
    )
    parser.add_argument(
        "--allow-unmet-deps",
        action="store_true",
        help="Allow starting even when depends_on jobs are not done (requires --decision-note).",
    )
    parser.add_argument(
        "--decision-note",
        default="",
        help="Required with --allow-unmet-deps; logged in project Decisions.",
    )
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    wi = args.work_item_id.strip()
    job_dir = find_job_dir(project_root, wi)
    plan_path = job_dir / "plan.md"

    ts = now_iso()

    proj = read_md(project_root / "plan.md")
    agree = str(proj.frontmatter.get("agreement_status") or "").strip()
    if agree != "agreed":
        raise SystemExit("agreement_status must be 'agreed' before job start (set it in project plan frontmatter).")
    proj_status = str(proj.frontmatter.get("status") or "planned").strip()
    if proj_status in {"done", "cancelled"}:
        raise SystemExit(f"Cannot start job while project status={proj_status!r}")

    ws_dir = parent_workstream_dir(project_root, job_dir)
    ws_doc = read_md(ws_dir / "plan.md")
    ws_id = str(ws_doc.frontmatter.get("id") or ws_dir.name).strip()
    ws_status = str(ws_doc.frontmatter.get("status") or "planned").strip()
    if ws_status in {"done", "cancelled"}:
        raise SystemExit(f"Cannot start job while parent workstream {ws_id} status={ws_status!r}")

    doc = read_md(plan_path)
    prev_status = str(doc.frontmatter.get("status") or "planned").strip()
    if prev_status in {"done", "cancelled"}:
        raise SystemExit(f"Cannot start job in status={prev_status!r}: {wi}")

    context_errors, context_warnings, context_ref = validate_context_gate_for_job(project_root, plan_path)
    if context_errors:
        raise SystemExit("Context gate failed:\n- " + "\n- ".join(context_errors))
    for warning in context_warnings:
        print(f"warning: {warning}", file=sys.stderr)

    deps = normalize_str_list(doc.frontmatter.get("depends_on"))
    dep_states = dependency_statuses(project_root, deps)
    unmet = [f"{dep}={state}" for dep, state in dep_states if state != "done"]
    if unmet and not args.allow_unmet_deps:
        raise SystemExit(
            "Cannot start job while dependencies are not done: "
            + ", ".join(unmet)
            + ". Resolve dependencies first, or use --allow-unmet-deps with --decision-note."
        )
    if unmet and args.allow_unmet_deps:
        if not str(args.decision_note or "").strip():
            raise SystemExit("--allow-unmet-deps requires --decision-note so the exception is explicitly recorded.")
        proj_doc = read_md(project_root / "plan.md")
        decision = (
            f"{ts}: dependency override for {wi}; unmet dependencies: {', '.join(unmet)}; "
            f"note: {args.decision_note.strip()}"
        )
        proj_doc.body = append_decision_log(proj_doc.body, decision)
        proj_doc.frontmatter["updated_at"] = ts
        write_md(project_root / "plan.md", proj_doc)
        doc.body = append_section_bullet(
            doc.body,
            "# Progress Log",
            f"{ts} dependency_override: {', '.join(unmet)}; note: {args.decision_note.strip()}",
        )
        write_md(plan_path, doc)

    lesson_progress = ""
    if not args.no_apply_lessons:
        try:
            lesson_result = apply_lessons_to_job(
                project_root,
                wi,
                limit=max(0, int(args.lessons_limit)),
                include_global=bool(args.lessons_include_global),
            )
            applied = [x for x in (lesson_result.get("applied_ids") or []) if str(x).strip()]
            if applied:
                lesson_progress = "lessons applied: " + ", ".join(applied[:5])
            elif str(lesson_result.get("status") or "") == "updated":
                lesson_progress = "lessons applied: section refreshed"
            else:
                lesson_progress = "lessons applied: no matching lessons"
        except Exception as exc:
            print(f"warning: lessons_apply failed; continuing without lesson update ({exc})", file=sys.stderr)

    # Reload after optional lessons mutation so iteration/status logic uses current state.
    doc = read_md(plan_path)

    try:
        iteration = int(doc.frontmatter.get("iteration") or 0)
    except Exception:
        iteration = 0
    if prev_status != "in_progress":
        if iteration <= 0:
            iteration = 1
        elif prev_status in {"planned", "blocked"}:
            iteration += 1

    extra_progress = [f"job_start: {prev_status} -> in_progress (iteration {iteration})"]
    if context_ref:
        extra_progress.insert(0, f"context gate: using {context_ref}")
    if lesson_progress:
        extra_progress.insert(0, lesson_progress)

    transition_entity(
        project_root,
        entity_kind="job",
        entity_id=wi,
        to_status="in_progress",
        reason="job start",
        actor="job_start.py",
        expected_from=prev_status,
        sync=not args.no_sync,
        refresh_dashboard=not args.no_dashboard,
        start_monitor=not args.no_monitor,
        monitor_policy_override=("manual" if args.no_open else ""),
        no_open=args.no_open,
        extra_frontmatter={"iteration": iteration},
        extra_progress=extra_progress,
    )

    # Keep orchestration model refreshed, but never block lifecycle transitions.
    try:
        from tw_tools import run_script

        run_script("orchestrate_plan.py", ["--project", str(project_root)], check=True)
    except Exception:
        pass

    print(wi)


if __name__ == "__main__":
    main()
