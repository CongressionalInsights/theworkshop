#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tw_tools import append_section_bullet, next_counter_id, rel_project_path, run_script, slugify
from twlib import now_iso, read_md, resolve_project_root, write_md
from twyaml import MarkdownDoc


def _today_yyyymmdd() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _run_shell(command: str, cwd: Path) -> tuple[int, str, str]:
    proc = subprocess.run(command, shell=True, cwd=str(cwd), text=True, capture_output=True)
    return int(proc.returncode), proc.stdout or "", proc.stderr or ""


def _write_run_log(path: Path, command: str, rc: int, stdout: str, stderr: str) -> None:
    lines = []
    lines.append(f"$ {command}")
    lines.append("")
    lines.append(f"exit_code={rc}")
    lines.append("")
    if stdout:
        lines.append("[stdout]")
        lines.append(stdout.rstrip())
        lines.append("")
    if stderr:
        lines.append("[stderr]")
        lines.append(stderr.rstrip())
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _render_summary(qid: str, title: str, results: list[dict[str, Any]], status: str) -> str:
    lines: list[str] = []
    lines.append("# Quick Task Summary")
    lines.append("")
    lines.append(f"- Quick ID: `{qid}`")
    lines.append(f"- Title: {title}")
    lines.append(f"- Status: `{status}`")
    lines.append("")
    lines.append("## Command Results")
    lines.append("")
    lines.append("| # | Command | Exit | Log |")
    lines.append("| --- | --- | --- | --- |")
    for i, r in enumerate(results, start=1):
        cmd = str(r.get("command") or "").replace("|", "\\|")
        exit_code = int(r.get("exit_code") or 0)
        log_path = str(r.get("log") or "")
        lines.append(f"| {i} | `{cmd}` | {exit_code} | `{log_path}` |")
    if not results:
        lines.append("| - | (no commands provided) | - | - |")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a short-path ad-hoc task in quick/<id> with summary artifacts.")
    parser.add_argument("description", nargs="*", help="Quick task description")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--title", help="Task title (defaults to positional description)")
    parser.add_argument("--command", action="append", default=[], help="Shell command to execute (repeatable)")
    parser.add_argument("--work-item-id", help="Optional WI-... linkage for quick task context")
    parser.add_argument("--no-dashboard", action="store_true", help="Skip dashboard rebuild")
    parser.add_argument("--no-open", action="store_true", help="Skip dashboard open")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    desc = (args.title or " ".join(args.description)).strip()
    if not desc:
        raise SystemExit("Provide quick task description via --title or positional text")

    quick_root = project_root / "quick"
    quick_root.mkdir(parents=True, exist_ok=True)

    date = _today_yyyymmdd()
    existing = [p.name for p in quick_root.iterdir() if p.is_dir()]
    qid = next_counter_id("QK", date, existing)
    slug = slugify(desc)
    task_dir = quick_root / f"{qid}-{slug}"
    logs_dir = task_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    ts = now_iso()
    commands = [str(c).strip() for c in args.command if str(c).strip()]

    plan_doc = MarkdownDoc(
        frontmatter={
            "schema": "theworkshop.quick.v1",
            "kind": "quick_task",
            "id": qid,
            "title": desc,
            "status": "in_progress" if commands else "planned",
            "work_item_id": str(args.work_item_id or "").strip(),
            "commands": commands,
            "created_at": ts,
            "updated_at": ts,
            "completed_at": "",
            "summary": "summary.md",
        },
        body="\n".join(
            [
                "# Objective",
                "",
                desc,
                "",
                "# Commands",
                "",
                *(f"- `{cmd}`" for cmd in commands),
                "" if commands else "- (none)",
                "",
                "# Progress Log",
                "",
                f"- {ts} quick task created",
                "",
            ]
        ),
    )
    write_md(task_dir / "plan.md", plan_doc)

    results: list[dict[str, Any]] = []
    overall_status = "planned" if not commands else "done"

    for idx, cmd in enumerate(commands, start=1):
        rc, out, err = _run_shell(cmd, project_root)
        log_rel = f"logs/{idx:02d}.log"
        _write_run_log(logs_dir / f"{idx:02d}.log", cmd, rc, out, err)
        results.append({"command": cmd, "exit_code": rc, "log": log_rel})
        if rc != 0:
            overall_status = "blocked"

    if commands and overall_status == "done":
        overall_status = "done"

    if commands:
        plan_doc = read_md(task_dir / "plan.md")
        plan_doc.frontmatter["status"] = overall_status
        plan_doc.frontmatter["updated_at"] = now_iso()
        plan_doc.frontmatter["completed_at"] = now_iso() if overall_status == "done" else ""
        plan_doc.body = append_section_bullet(
            plan_doc.body,
            "# Progress Log",
            f"{now_iso()} quick execution finished with status={overall_status}",
        )
        write_md(task_dir / "plan.md", plan_doc)

    summary = _render_summary(qid, desc, results, overall_status)
    (task_dir / "summary.md").write_text(summary, encoding="utf-8")

    # Keep main project control plane aware without changing rollup semantics.
    project_plan = project_root / "plan.md"
    proj_doc = read_md(project_plan)
    proj_doc.body = append_section_bullet(
        proj_doc.body,
        "# Progress Log",
        f"{now_iso()} quick task `{qid}` ({overall_status}) -> `{rel_project_path(project_root, task_dir / 'summary.md')}`",
    )
    proj_doc.frontmatter["updated_at"] = now_iso()
    write_md(project_plan, proj_doc)

    if not args.no_dashboard:
        try:
            run_script("dashboard_projector.py", ["--project", str(project_root)])
        except Exception:
            pass

    if not args.no_open:
        try:
            run_script("dashboard_open.py", ["--project", str(project_root), "--once"])
        except Exception:
            pass

    print(rel_project_path(project_root, task_dir / "summary.md"))


if __name__ == "__main__":
    main()
