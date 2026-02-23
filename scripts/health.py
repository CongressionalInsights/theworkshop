#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from tw_tools import (
    ensure_dirs,
    parse_markdown_safe,
    read_json,
    rel_project_path,
    run_script,
    validate_context_gate_for_job,
    write_json,
)
from twlib import list_job_dirs, list_workstream_dirs, normalize_str_list, now_iso, read_md, resolve_project_root


@dataclass
class Issue:
    code: str
    severity: str  # error|warning|info
    message: str
    fix: str
    repairable: bool
    path: str = ""


def _add(issues: list[Issue], code: str, severity: str, message: str, fix: str, repairable: bool, path: str = "") -> None:
    issues.append(Issue(code=code, severity=severity, message=message, fix=fix, repairable=repairable, path=path))


def _check_job_cycles(job_deps: dict[str, list[str]]) -> list[list[str]]:
    visited: set[str] = set()
    active: set[str] = set()
    stack: list[str] = []
    cycles: list[list[str]] = []

    def dfs(node: str) -> None:
        if node in active:
            if node in stack:
                idx = stack.index(node)
                cycles.append(stack[idx:] + [node])
            return
        if node in visited:
            return

        visited.add(node)
        active.add(node)
        stack.append(node)
        for dep in job_deps.get(node, []):
            if dep in job_deps:
                dfs(dep)
        stack.pop()
        active.remove(node)

    for wi in sorted(job_deps.keys()):
        dfs(wi)
    return cycles


def _health_report(project_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    ts = now_iso()
    issues: list[Issue] = []
    repairs_suggested: list[dict[str, Any]] = []
    repairs_performed: list[dict[str, Any]] = []

    required_paths = [
        project_root / "plan.md",
        project_root / "workstreams" / "index.md",
    ]
    for p in required_paths:
        if not p.exists():
            _add(
                issues,
                "E001",
                "error",
                f"Missing required file: {rel_project_path(project_root, p)}",
                "Recreate project skeleton with project_new.py or restore the missing file.",
                False,
                rel_project_path(project_root, p),
            )

    # Optional but expected control-plane docs.
    optional_paths = [
        project_root / "notes" / "lessons-learned.md",
        project_root / "notes" / "context",
        project_root / "outputs" / "uat",
        project_root / "quick",
    ]
    for p in optional_paths:
        if p.exists():
            continue
        _add(
            issues,
            "W010",
            "warning",
            f"Missing optional control-plane path: {rel_project_path(project_root, p)}",
            "Run `theworkshop health --repair` to create this path.",
            True,
            rel_project_path(project_root, p),
        )
        repairs_suggested.append({"action": "create_path", "path": rel_project_path(project_root, p)})

    # Parse project plan.
    project_plan = project_root / "plan.md"
    proj_doc, proj_err = parse_markdown_safe(project_plan)
    if proj_err:
        _add(
            issues,
            "E002",
            "error",
            proj_err,
            "Fix malformed frontmatter in plan.md manually.",
            False,
            rel_project_path(project_root, project_plan),
        )
        payload = {
            "schema": "theworkshop.health.v1",
            "generated_at": ts,
            "project": str(project_root),
            "status": "broken",
            "errors": [asdict(i) for i in issues if i.severity == "error"],
            "warnings": [asdict(i) for i in issues if i.severity == "warning"],
            "info": [asdict(i) for i in issues if i.severity == "info"],
            "repairable_count": sum(1 for i in issues if i.repairable),
            "repairs_suggested": repairs_suggested,
            "repairs_performed": repairs_performed,
        }
        return payload, repairs_suggested, repairs_performed

    assert proj_doc is not None
    if str(proj_doc.frontmatter.get("kind") or "") != "project":
        _add(
            issues,
            "E003",
            "error",
            "plan.md frontmatter kind must be 'project'",
            "Fix plan.md frontmatter kind.",
            False,
            rel_project_path(project_root, project_plan),
        )

    # Scan workstreams and jobs.
    ws_id_to_path: dict[str, Path] = {}
    job_id_to_path: dict[str, Path] = {}
    job_deps: dict[str, list[str]] = {}

    for ws_dir in list_workstream_dirs(project_root):
        ws_plan = ws_dir / "plan.md"
        ws_doc, ws_err = parse_markdown_safe(ws_plan)
        if ws_err:
            _add(
                issues,
                "E011",
                "error",
                ws_err,
                "Fix malformed workstream frontmatter manually.",
                False,
                rel_project_path(project_root, ws_plan),
            )
            continue
        assert ws_doc is not None
        ws_id = str(ws_doc.frontmatter.get("id") or "").strip()
        if not ws_id:
            _add(
                issues,
                "E012",
                "error",
                "Workstream is missing frontmatter id",
                "Set workstream id in frontmatter.",
                False,
                rel_project_path(project_root, ws_plan),
            )
        else:
            if ws_id in ws_id_to_path:
                _add(
                    issues,
                    "E013",
                    "error",
                    f"Duplicate workstream id {ws_id}",
                    "Rename one workstream id and align references.",
                    False,
                    rel_project_path(project_root, ws_plan),
                )
            ws_id_to_path[ws_id] = ws_plan
            if not ws_dir.name.startswith(ws_id):
                _add(
                    issues,
                    "W013",
                    "warning",
                    f"Workstream directory does not match id {ws_id}",
                    "Rename directory to match workstream id prefix.",
                    False,
                    rel_project_path(project_root, ws_dir),
                )

        declared_jobs = normalize_str_list(ws_doc.frontmatter.get("jobs"))

        found_jobs: list[str] = []
        for job_dir in list_job_dirs(ws_dir):
            job_plan = job_dir / "plan.md"
            job_doc, job_err = parse_markdown_safe(job_plan)
            if job_err:
                _add(
                    issues,
                    "E021",
                    "error",
                    job_err,
                    "Fix malformed job frontmatter manually.",
                    False,
                    rel_project_path(project_root, job_plan),
                )
                continue
            assert job_doc is not None
            wi = str(job_doc.frontmatter.get("work_item_id") or "").strip()
            if not wi:
                _add(
                    issues,
                    "E022",
                    "error",
                    "Job is missing frontmatter work_item_id",
                    "Set work_item_id in job frontmatter.",
                    False,
                    rel_project_path(project_root, job_plan),
                )
                continue

            found_jobs.append(wi)
            if wi in job_id_to_path:
                _add(
                    issues,
                    "E023",
                    "error",
                    f"Duplicate work_item_id {wi}",
                    "Rename one job id and align dependencies.",
                    False,
                    rel_project_path(project_root, job_plan),
                )
            job_id_to_path[wi] = job_plan

            if not job_dir.name.startswith(wi):
                _add(
                    issues,
                    "W023",
                    "warning",
                    f"Job directory does not match work_item_id {wi}",
                    "Rename directory to match work_item_id prefix.",
                    False,
                    rel_project_path(project_root, job_dir),
                )

            deps = normalize_str_list(job_doc.frontmatter.get("depends_on"))
            job_deps[wi] = deps

            # Context gate health.
            ctx_errors, ctx_warnings, _ctx_ref = validate_context_gate_for_job(project_root, job_plan)
            for msg in ctx_errors:
                _add(
                    issues,
                    "E024",
                    "error",
                    msg,
                    "Capture context with `theworkshop discuss --work-item-id ... --required`.",
                    False,
                    rel_project_path(project_root, job_plan),
                )
            for msg in ctx_warnings:
                _add(
                    issues,
                    "W024",
                    "warning",
                    msg,
                    "Review context linkage and update context_ref if needed.",
                    False,
                    rel_project_path(project_root, job_plan),
                )

            status = str(job_doc.frontmatter.get("status") or "planned").strip()
            if status == "done" and not str(job_doc.frontmatter.get("completed_at") or "").strip():
                _add(
                    issues,
                    "W025",
                    "warning",
                    "Job status is done but completed_at is empty",
                    "Set completed_at or rerun completion flow.",
                    False,
                    rel_project_path(project_root, job_plan),
                )

            # Optional artifact safety checks.
            outputs = normalize_str_list(job_doc.frontmatter.get("outputs"))
            evidence = normalize_str_list(job_doc.frontmatter.get("verification_evidence"))
            for rel in outputs + evidence:
                p = job_dir / rel
                if p.exists():
                    continue
                _add(
                    issues,
                    "I030",
                    "info",
                    f"Missing declared artifact path: {rel}",
                    "Run `theworkshop health --repair` to create safe placeholders for non-done jobs.",
                    True,
                    rel_project_path(project_root, job_plan),
                )
                repairs_suggested.append(
                    {
                        "action": "create_artifact_placeholder",
                        "work_item_id": wi,
                        "path": rel,
                        "allowed_when_status": "not done",
                    }
                )

        for missing_declared in sorted(set(declared_jobs) - set(found_jobs)):
            _add(
                issues,
                "W014",
                "warning",
                f"Workstream jobs list references missing job {missing_declared}",
                "Run plan_sync.py to regenerate jobs table/frontmatter references.",
                True,
                rel_project_path(project_root, ws_plan),
            )
            repairs_suggested.append({"action": "regenerate_sync", "workstream": ws_id or ws_dir.name})

    # Dependency existence checks.
    for wi, deps in job_deps.items():
        for dep in deps:
            if dep in job_id_to_path:
                continue
            _add(
                issues,
                "E031",
                "error",
                f"Job dependency missing: {wi} depends_on {dep}",
                "Fix depends_on references or create the missing job.",
                False,
                rel_project_path(project_root, job_id_to_path.get(wi, project_root)),
            )

    # Dependency cycle checks.
    for cycle in _check_job_cycles(job_deps):
        _add(
            issues,
            "E032",
            "error",
            "Dependency cycle detected: " + " -> ".join(cycle),
            "Break the cycle by removing at least one depends_on edge.",
            False,
        )

    # UAT run references stale jobs.
    for uat_json in sorted((project_root / "outputs" / "uat").glob("*-UAT.json")):
        payload = read_json(uat_json, {})
        if not isinstance(payload, dict):
            continue
        for t in payload.get("tests") or []:
            wi = str((t or {}).get("work_item_id") or "").strip()
            if wi and wi not in job_id_to_path:
                _add(
                    issues,
                    "W040",
                    "warning",
                    f"UAT run references unknown work item {wi}",
                    "Start a new verify-work run or clean stale UAT artifacts.",
                    False,
                    rel_project_path(project_root, uat_json),
                )

    # Orchestration stale references.
    orch = read_json(project_root / "outputs" / "orchestration.json", {})
    if isinstance(orch, dict):
        groups = orch.get("parallel_groups") or orch.get("groups") or []
        stale: set[str] = set()
        if isinstance(groups, list):
            for group in groups:
                if isinstance(group, list):
                    for wi in group:
                        s = str(wi).strip()
                        if s and s not in job_id_to_path:
                            stale.add(s)
        if stale:
            _add(
                issues,
                "W050",
                "warning",
                "orchestration.json references non-existent jobs: " + ", ".join(sorted(stale)[:10]),
                "Run `theworkshop orchestrate --project ...` to regenerate orchestration output.",
                True,
                rel_project_path(project_root, project_root / "outputs" / "orchestration.json"),
            )
            repairs_suggested.append({"action": "rebuild_orchestration"})

    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    status = "healthy"
    if errors:
        status = "broken"
    elif warnings:
        status = "degraded"

    payload = {
        "schema": "theworkshop.health.v1",
        "generated_at": ts,
        "project": str(project_root),
        "status": status,
        "errors": [asdict(i) for i in errors],
        "warnings": [asdict(i) for i in warnings],
        "info": [asdict(i) for i in issues if i.severity == "info"],
        "repairable_count": sum(1 for i in issues if i.repairable),
        "repairs_suggested": repairs_suggested,
        "repairs_performed": repairs_performed,
    }
    return payload, repairs_suggested, repairs_performed


def _safe_repair(project_root: Path) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []

    # 1) Ensure control-plane paths exist.
    ensure_dirs(
        [
            project_root / "notes" / "context",
            project_root / "outputs" / "uat",
            project_root / "quick",
            project_root / "outputs",
        ]
    )
    actions.append({"action": "ensure_control_plane_paths"})

    lessons = project_root / "notes" / "lessons-learned.md"
    if not lessons.exists():
        lessons.parent.mkdir(parents=True, exist_ok=True)
        lessons.write_text("# Lessons Learned\n\n", encoding="utf-8")
        actions.append({"action": "create_file", "path": "notes/lessons-learned.md"})

    # 2) Create safe artifact placeholders only for non-done jobs.
    for ws_dir in list_workstream_dirs(project_root):
        for job_dir in list_job_dirs(ws_dir):
            plan_path = job_dir / "plan.md"
            try:
                doc = read_md(plan_path)
            except Exception:
                continue
            status = str(doc.frontmatter.get("status") or "planned").strip()
            if status == "done":
                continue

            declared = normalize_str_list(doc.frontmatter.get("outputs")) + normalize_str_list(
                doc.frontmatter.get("verification_evidence")
            )
            for rel in declared:
                p = job_dir / rel
                p.parent.mkdir(parents=True, exist_ok=True)
                if p.exists():
                    continue
                if p.suffix.lower() == ".md":
                    p.write_text(
                        "\n".join(
                            [
                                "# Placeholder",
                                "",
                                "Auto-created by `theworkshop health --repair`.",
                                "Replace with real output/evidence before completion.",
                                "",
                            ]
                        ),
                        encoding="utf-8",
                    )
                else:
                    p.touch()
                actions.append({"action": "create_artifact_placeholder", "path": rel})

    # 3) Rebuild derived artifacts.
    for script, argv in [
        ("plan_sync.py", ["--project", str(project_root)]),
        ("task_tracker_build.py", ["--project", str(project_root)]),
        ("orchestrate_plan.py", ["--project", str(project_root)]),
        ("dashboard_build.py", ["--project", str(project_root)]),
    ]:
        try:
            run_script(script, argv)
            actions.append({"action": "run", "script": script})
        except Exception as exc:
            actions.append({"action": "run", "script": script, "status": "failed", "error": str(exc)})

    return actions


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate project topology and state integrity; optional safe repairs.")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--repair", action="store_true", help="Perform safe auto-repairs")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)

    repair_actions: list[dict[str, Any]] = []
    if args.repair:
        repair_actions = _safe_repair(project_root)

    report, _suggested, _performed = _health_report(project_root)
    if repair_actions:
        report["repairs_performed"] = repair_actions

    out_path = project_root / "outputs" / "health.json"
    write_json(out_path, report)

    print(f"Status: {report.get('status')}")
    print(f"Errors: {len(report.get('errors') or [])}")
    print(f"Warnings: {len(report.get('warnings') or [])}")
    print(f"Info: {len(report.get('info') or [])}")
    if report.get("repairable_count"):
        print(f"Repairable: {report.get('repairable_count')}")
    print(rel_project_path(project_root, out_path))

    if report.get("status") == "broken":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
