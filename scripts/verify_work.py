#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tw_tools import (
    append_section_bullet,
    extract_section_bullets,
    find_job_dir,
    read_json,
    rel_project_path,
    run_script,
    slugify,
    write_json,
)
from twlib import list_job_dirs, list_workstream_dirs, now_iso, read_md, resolve_project_root, write_md


PASS_WORDS = {"", "pass", "yes", "y", "ok", "approved", "next"}
SKIP_PREFIXES = ("skip", "n/a", "na", "cant-test", "cannot-test")


def _today_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _infer_severity(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["crash", "exception", "fatal", "broken", "unusable", "data loss"]):
        return "blocker"
    if any(k in t for k in ["doesn't", "doesnt", "missing", "fails", "can't", "cannot", "wrong"]):
        return "major"
    if any(k in t for k in ["slow", "weird", "minor", "off", "inconsistent"]):
        return "minor"
    if any(k in t for k in ["alignment", "font", "spacing", "color", "visual"]):
        return "cosmetic"
    return "major"


def _parse_response_token(token: str) -> tuple[str, str]:
    s = token.strip()
    if not s:
        return "pass", ""
    lower = s.lower()
    if lower in PASS_WORDS:
        return "pass", ""
    if any(lower.startswith(prefix) for prefix in SKIP_PREFIXES):
        reason = ""
        if ":" in s:
            reason = s.split(":", 1)[1].strip()
        return "skip", reason
    # Explicit fail shorthand: fail:...
    if lower.startswith("fail:"):
        return "fail", s.split(":", 1)[1].strip()
    return "fail", s


def _target_jobs(project_root: Path, work_item_id: str | None) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for ws_dir in list_workstream_dirs(project_root):
        for job_dir in list_job_dirs(ws_dir):
            doc = read_md(job_dir / "plan.md")
            wi = str(doc.frontmatter.get("work_item_id") or "").strip()
            if not wi:
                continue
            if work_item_id and wi != work_item_id:
                continue
            status = str(doc.frontmatter.get("status") or "planned").strip()
            if not work_item_id and status == "cancelled":
                continue
            jobs.append(
                {
                    "work_item_id": wi,
                    "title": str(doc.frontmatter.get("title") or "").strip(),
                    "status": status,
                    "job_dir": job_dir,
                    "plan_doc": doc,
                }
            )
    return jobs


def _tests_from_job(job: dict[str, Any]) -> list[dict[str, Any]]:
    wi = str(job["work_item_id"])
    doc = job["plan_doc"]
    bullets = extract_section_bullets(doc.body, "# Acceptance Criteria")
    tests: list[dict[str, Any]] = []

    if not bullets:
        tests.append(
            {
                "work_item_id": wi,
                "name": f"{wi} declared outputs are present",
                "expected": "Declared outputs and verification evidence are non-empty.",
                "status": "pending",
                "response": "",
                "severity": "",
                "follow_up": "",
            }
        )
        return tests

    for idx, bullet in enumerate(bullets, start=1):
        tests.append(
            {
                "work_item_id": wi,
                "name": f"{wi} acceptance criterion {idx}",
                "expected": bullet,
                "status": "pending",
                "response": "",
                "severity": "",
                "follow_up": "",
            }
        )
    return tests


def _build_tests(project_root: Path, work_item_id: str | None) -> list[dict[str, Any]]:
    tests: list[dict[str, Any]] = []
    for job in _target_jobs(project_root, work_item_id):
        tests.extend(_tests_from_job(job))
    return tests


def _target_label(project_root: Path, work_item_id: str | None) -> tuple[str, str]:
    if work_item_id:
        return "job", work_item_id
    proj = read_md(project_root / "plan.md")
    pid = str(proj.frontmatter.get("id") or "PROJECT")
    return "project", pid


def _find_active_run(uat_dir: Path, target_kind: str, target_id: str) -> str | None:
    candidates = sorted(uat_dir.glob("*-UAT.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in candidates:
        payload = read_json(p, {})
        if not isinstance(payload, dict):
            continue
        if payload.get("target_kind") != target_kind:
            continue
        if payload.get("target_id") != target_id:
            continue
        if str(payload.get("status") or "") == "testing":
            return str(payload.get("run_id") or "")
    return None


def _run_paths(uat_dir: Path, run_id: str) -> tuple[Path, Path]:
    return uat_dir / f"{run_id}-UAT.json", uat_dir / f"{run_id}-UAT.md"


def _render_markdown(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# UAT Run")
    lines.append("")
    lines.append(f"- Run ID: `{payload.get('run_id', '')}`")
    lines.append(f"- Target: `{payload.get('target_kind', '')}` `{payload.get('target_id', '')}`")
    lines.append(f"- Status: `{payload.get('status', '')}`")
    lines.append(f"- Updated: `{payload.get('updated_at', '')}`")
    lines.append("")

    summary = payload.get("summary") or {}
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Total: {summary.get('total', 0)}")
    lines.append(f"- Passed: {summary.get('passed', 0)}")
    lines.append(f"- Failed: {summary.get('failed', 0)}")
    lines.append(f"- Skipped: {summary.get('skipped', 0)}")
    lines.append(f"- Pending: {summary.get('pending', 0)}")
    lines.append("")

    lines.append("## Tests")
    lines.append("")
    tests = payload.get("tests") or []
    for i, t in enumerate(tests, start=1):
        lines.append(f"### {i}. {t.get('name', '')}")
        lines.append("")
        lines.append(f"- Work Item: `{t.get('work_item_id', '')}`")
        lines.append(f"- Expected: {t.get('expected', '')}")
        lines.append(f"- Status: `{t.get('status', '')}`")
        response = str(t.get("response") or "")
        if response:
            lines.append(f"- Response: {response}")
        severity = str(t.get("severity") or "")
        if severity:
            lines.append(f"- Severity: `{severity}`")
        follow_up = str(t.get("follow_up") or "")
        if follow_up:
            lines.append(f"- Follow Up: {follow_up}")
        lines.append("")

    issues = payload.get("open_issues") or []
    lines.append("## Open Issues")
    lines.append("")
    if not issues:
        lines.append("- (none)")
        lines.append("")
    else:
        for issue in issues:
            lines.append(
                f"- `{issue.get('work_item_id','')}` [{issue.get('severity','major')}]: {issue.get('reason','')}"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _update_summary(payload: dict[str, Any]) -> None:
    tests = payload.get("tests") or []
    total = len(tests)
    passed = sum(1 for t in tests if t.get("status") == "pass")
    failed = sum(1 for t in tests if t.get("status") == "fail")
    skipped = sum(1 for t in tests if t.get("status") == "skip")
    pending = sum(1 for t in tests if t.get("status") == "pending")
    payload["summary"] = {
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "pending": pending,
    }


def _persist(uat_json: Path, uat_md: Path, payload: dict[str, Any]) -> None:
    payload["updated_at"] = now_iso()
    _update_summary(payload)
    write_json(uat_json, payload)
    uat_md.write_text(_render_markdown(payload), encoding="utf-8")


def _parse_responses(raw: str) -> list[str]:
    out: list[str] = []
    if not raw.strip():
        return out
    for part in raw.split(","):
        token = part.strip()
        if token:
            out.append(token)
    return out


def _apply_job_uat_updates(project_root: Path, payload: dict[str, Any]) -> list[str]:
    """Write UAT status/issues into job frontmatter and progress logs."""
    tests = payload.get("tests") or []
    by_wi: dict[str, list[dict[str, Any]]] = {}
    for t in tests:
        wi = str(t.get("work_item_id") or "").strip()
        if not wi:
            continue
        by_wi.setdefault(wi, []).append(t)

    updated_wis: list[str] = []
    for wi, items in by_wi.items():
        fails = [x for x in items if x.get("status") == "fail"]
        open_issues = [str(x.get("response") or x.get("expected") or "").strip() for x in fails if str(x.get("response") or x.get("expected") or "").strip()]
        follow_up = [str(x.get("follow_up") or "").strip() for x in fails if str(x.get("follow_up") or "").strip()]

        job_dir = find_job_dir(project_root, wi)
        plan_path = job_dir / "plan.md"
        doc = read_md(plan_path)
        doc.frontmatter["uat_last_status"] = "fail" if fails else "pass"
        doc.frontmatter["uat_last_checked_at"] = now_iso()
        doc.frontmatter["uat_open_issues"] = open_issues
        doc.frontmatter["uat_follow_up_actions"] = follow_up
        doc.frontmatter["updated_at"] = now_iso()

        if fails:
            doc.body = append_section_bullet(
                doc.body,
                "# Progress Log",
                f"{now_iso()} verify-work: {len(fails)} UAT issue(s) logged; completion gate will block until resolved",
            )
        else:
            doc.body = append_section_bullet(doc.body, "# Progress Log", f"{now_iso()} verify-work: UAT checks passed")

        write_md(plan_path, doc)
        updated_wis.append(wi)

    return updated_wis


def main() -> None:
    parser = argparse.ArgumentParser(description="Resumable conversational UAT for TheWorkshop jobs.")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--work-item-id", help="Run UAT for one job (WI-...) only")
    parser.add_argument("--run-id", help="Resume specific UAT run id")
    parser.add_argument("--start-new", action="store_true", help="Ignore active run and create a new one")
    parser.add_argument("--responses", default="", help="Comma-separated scripted responses for non-interactive use")
    parser.add_argument("--non-interactive", action="store_true", help="Do not prompt for input when scripted responses are exhausted")
    parser.add_argument("--no-sync", action="store_true", help="Skip plan sync after writing UAT results")
    parser.add_argument("--no-dashboard", action="store_true", help="Skip dashboard rebuild after UAT")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    uat_dir = project_root / "outputs" / "uat"
    uat_dir.mkdir(parents=True, exist_ok=True)

    target_kind, target_id = _target_label(project_root, args.work_item_id)

    run_id = str(args.run_id or "").strip()
    if not run_id and not args.start_new:
        run_id = _find_active_run(uat_dir, target_kind, target_id) or ""
    if not run_id:
        base = slugify(f"{target_id}-{_today_compact()}")
        run_id = f"{base}"

    uat_json, uat_md = _run_paths(uat_dir, run_id)
    payload = read_json(uat_json, {})

    if not payload:
        tests = _build_tests(project_root, args.work_item_id)
        if not tests:
            raise SystemExit("No testable jobs found for verify-work")
        payload = {
            "schema": "theworkshop.uat.v1",
            "run_id": run_id,
            "target_kind": target_kind,
            "target_id": target_id,
            "status": "testing",
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "current_index": 0,
            "tests": tests,
            "summary": {},
            "open_issues": [],
        }
        _persist(uat_json, uat_md, payload)

    if payload.get("status") == "completed":
        print(rel_project_path(project_root, uat_md))
        return

    scripted = _parse_responses(args.responses)
    scripted_idx = 0

    tests = payload.get("tests") or []
    cur = int(payload.get("current_index") or 0)

    while cur < len(tests):
        test = tests[cur]
        print("")
        print(f"Test {cur + 1}/{len(tests)}: {test.get('name','')}")
        print(f"Work Item: {test.get('work_item_id','')}")
        print(f"Expected: {test.get('expected','')}")

        if scripted_idx < len(scripted):
            raw = scripted[scripted_idx]
            scripted_idx += 1
            print(f"Response (scripted): {raw}")
        else:
            if args.non_interactive or not sys.stdin.isatty():
                break
            try:
                raw = input("Result (pass / skip[:reason] / fail[:issue]): ").strip()
            except EOFError:
                break

        status, detail = _parse_response_token(raw)
        if status == "pass":
            test["status"] = "pass"
            test["response"] = ""
            test["severity"] = ""
            test["follow_up"] = ""
        elif status == "skip":
            test["status"] = "skip"
            test["response"] = detail or "skipped"
            test["severity"] = ""
            test["follow_up"] = ""
        else:
            issue_text = detail or "UAT failed"
            severity = _infer_severity(issue_text)
            wi = str(test.get("work_item_id") or "")
            follow = f"Resolve UAT issue for {wi}: {test.get('expected','')} (reported: {issue_text})"
            test["status"] = "fail"
            test["response"] = issue_text
            test["severity"] = severity
            test["follow_up"] = follow

        tests[cur] = test
        cur += 1
        payload["current_index"] = cur

        open_issues = []
        for t in tests:
            if t.get("status") != "fail":
                continue
            open_issues.append(
                {
                    "work_item_id": str(t.get("work_item_id") or ""),
                    "severity": str(t.get("severity") or "major"),
                    "reason": str(t.get("response") or t.get("expected") or "").strip(),
                    "follow_up": str(t.get("follow_up") or "").strip(),
                }
            )
        payload["open_issues"] = open_issues
        payload["tests"] = tests

        _persist(uat_json, uat_md, payload)

    if int(payload.get("current_index") or 0) >= len(tests):
        payload["status"] = "completed"
        payload["updated_at"] = now_iso()
        _persist(uat_json, uat_md, payload)

    # Push structured follow-up actions into job plans + gates.
    updated_wis = _apply_job_uat_updates(project_root, payload)

    # Feed reward scoring and completion gating with fresh UAT status.
    for wi in updated_wis:
        try:
            run_script("reward_eval.py", ["--project", str(project_root), "--work-item-id", wi, "--no-sync", "--no-dashboard"])
        except Exception:
            pass

    if not args.no_sync:
        try:
            run_script("plan_sync.py", ["--project", str(project_root)])
        except Exception:
            pass

    if not args.no_dashboard:
        try:
            run_script("dashboard_build.py", ["--project", str(project_root)])
        except Exception:
            pass

    print(rel_project_path(project_root, uat_md))


if __name__ == "__main__":
    main()
