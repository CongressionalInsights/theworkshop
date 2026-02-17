#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from plan_sync import sync_project_plans
from truth_eval import evaluate_job_truth
from twlib import (
    estimate_token_proxy,
    list_job_dirs,
    list_workstream_dirs,
    load_job,
    now_iso,
    read_md,
    resolve_project_root,
    write_md,
)


def extract_section(body: str, heading: str) -> str:
    lines = body.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.strip() == heading.strip():
            start = i + 1
            break
    if start is None:
        return ""
    out = []
    for ln in lines[start:]:
        if ln.startswith("# "):
            break
        out.append(ln)
    return "\n".join(out).strip()


def looks_placeholder(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return True
    if "to be filled" in t:
        return True
    if "state the objective" in t or "make these objective" in t:
        return True
    if t.startswith("_") and t.endswith("_") and len(t) < 120:
        return True
    return False


def file_exists_nonempty(path: Path) -> bool:
    try:
        return path.exists() and path.is_file() and path.stat().st_size > 0
    except Exception:
        return False


def append_progress_log(body: str, line: str) -> str:
    # Append bullet to the Progress Log section (best effort).
    heading = "# Progress Log"
    if heading not in body:
        return body.rstrip() + "\n\n" + heading + "\n\n" + f"- {line}\n"
    parts = body.split(heading, 1)
    pre = parts[0]
    rest = parts[1]
    rest_lines = rest.splitlines()
    # Find insertion point: before next "# " heading after the first linebreak.
    insert_at = len(rest_lines)
    for i, ln in enumerate(rest_lines[1:], start=1):
        if ln.startswith("# "):
            insert_at = i
            break
    new_rest_lines = rest_lines[:insert_at] + [f"- {line}"] + rest_lines[insert_at:]
    return pre + heading + "\n" + "\n".join(new_rest_lines).rstrip() + "\n"


def compute_job_score(project_root: Path, job_dir: Path) -> dict:
    plan_path = job_dir / "plan.md"
    doc = read_md(plan_path)
    fm = doc.frontmatter
    wi = str(fm.get("work_item_id") or "").strip()

    outputs = fm.get("outputs", []) or []
    if isinstance(outputs, str):
        outputs = [o.strip() for o in outputs.split(",") if o.strip()]
    outputs = [str(o) for o in outputs]
    outputs_ok = [o for o in outputs if file_exists_nonempty(job_dir / o)]

    evid = fm.get("verification_evidence", []) or []
    if isinstance(evid, str):
        evid = [e.strip() for e in evid.split(",") if e.strip()]
    evid = [str(e) for e in evid]
    evid_ok = [e for e in evid if file_exists_nonempty(job_dir / e)]

    acceptance_text = extract_section(doc.body, "# Acceptance Criteria")
    verification_text = extract_section(doc.body, "# Verification")
    lessons_text = extract_section(doc.body, "# Relevant Lessons Learned")

    # 0–40: acceptance + outputs
    acceptance_score = 0
    if not looks_placeholder(acceptance_text):
        acceptance_score = 10 if len(acceptance_text) < 40 else 20
    outputs_score = 0
    if outputs:
        outputs_score = round(20 * (len(outputs_ok) / max(1, len(outputs))))
    score_a = acceptance_score + outputs_score

    # 0–20: verification plan + evidence
    ver_plan_score = 0
    if not looks_placeholder(verification_text):
        ver_plan_score = 5 if len(verification_text) < 40 else 10
    ver_evid_score = 0
    if evid:
        ver_evid_score = round(10 * (len(evid_ok) / max(1, len(evid))))
    score_v = ver_plan_score + ver_evid_score

    # 0–10: plan hygiene
    score_h = 0
    status = str(fm.get("status") or "planned").strip()
    started_at = str(fm.get("started_at") or "").strip()
    completed_at = str(fm.get("completed_at") or "").strip()
    updated_at = str(fm.get("updated_at") or "").strip()
    progress_log_text = extract_section(doc.body, "# Progress Log")
    progress_lower = progress_log_text.lower()
    if status in {"in_progress", "blocked", "done"} and started_at:
        score_h += 2
    if updated_at:
        score_h += 2
    if progress_log_text.strip():
        score_h += 2
    # Avoid a deadlock where high-stakes jobs cannot reach target until after done.
    # Completion-readiness evidence in the progress log can satisfy this slot pre-done.
    if status == "done" and completed_at:
        score_h += 2
    elif status in {"in_progress", "blocked"} and (
        "job_complete: attempting completion" in progress_lower or "qa note:" in progress_lower
    ):
        score_h += 2
    if status in {"planned", "in_progress", "blocked", "done"}:
        score_h += 2

    # 0–10: tracker + dashboard
    score_td = 0
    dash_json = project_root / "outputs" / "dashboard.json"
    dash_html = project_root / "outputs" / "dashboard.html"
    tracker = sorted((project_root / "outputs").glob("*-task-tracker.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if dash_json.exists() and dash_html.exists():
        score_td += 5
    if tracker:
        score_td += 5

    # 0–5: lessons applied + captured
    score_l = 0
    if not looks_placeholder(lessons_text):
        score_l += 2
    lessons_path = project_root / "notes" / "lessons-learned.md"
    if lessons_path.exists():
        try:
            content = lessons_path.read_text(encoding="utf-8", errors="ignore")
            if wi and wi in content:
                score_l += 3
        except Exception:
            pass

    # 0–10: execution log health
    score_log = 0
    exec_log = project_root / "logs" / "execution.jsonl"
    entries = []
    if exec_log.exists():
        for ln in exec_log.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not ln.strip():
                continue
            try:
                entries.append(json.loads(ln))
            except Exception:
                continue
    wi_entries = [e for e in entries if str(e.get("work_item_id") or "") == wi]
    if wi_entries:
        score_log += 5
        failures = [e for e in wi_entries if int(e.get("exit_code", 0)) != 0]
        fail_rate = len(failures) / max(1, len(wi_entries))
        score_log += round(5 * (1.0 - fail_rate))

    # 0–5: GitHub parity (best-effort)
    score_gh = 0
    proj = read_md(project_root / "plan.md")
    if bool(proj.frontmatter.get("github_enabled")):
        gm = project_root / "notes" / "github-map.json"
        if gm.exists():
            try:
                payload = json.loads(gm.read_text(encoding="utf-8"))
                issues = payload.get("issues", {}) or {}
                if wi in issues:
                    score_gh = 5
            except Exception:
                pass

    base = score_a + score_v + score_h + score_td + score_l + score_log + score_gh

    # Penalties
    penalties = 0
    try:
        rework = int(fm.get("rework_count") or 0)
        penalties -= min(10, 2 * max(0, rework))
    except Exception:
        pass
    try:
        iteration = int(fm.get("iteration") or 0)
        max_iter = int(fm.get("max_iterations") or 0)
        if max_iter and iteration > max_iter:
            penalties -= 10
    except Exception:
        pass

    total = max(0, min(100, int(round(base + penalties))))

    truth = evaluate_job_truth(project_root, job_dir)
    truth_pass = str(truth.get("truth_status") or "fail") == "pass"
    truth_failures = [str(x) for x in (truth.get("failures") or [])]

    # Next action hints (deterministic)
    next_action = ""
    if not truth_pass:
        next_action = "Truth gate failed: " + (truth_failures[0] if truth_failures else "run truth_eval.py and fix failing checks.")
    elif outputs and len(outputs_ok) < len(outputs):
        missing = [o for o in outputs if o not in outputs_ok]
        next_action = "Create missing outputs: " + ", ".join(missing[:5])
    elif evid and len(evid_ok) < len(evid):
        missing = [e for e in evid if e not in evid_ok]
        next_action = "Produce verification evidence: " + ", ".join(missing[:5])
    elif looks_placeholder(acceptance_text):
        next_action = "Tighten acceptance criteria into objective, checkable bullets."
    elif looks_placeholder(verification_text):
        next_action = "Write a concrete verification plan and declare evidence files."
    elif not (dash_json.exists() and dash_html.exists()):
        next_action = "Run dashboard_build.py to refresh dashboard artifacts."
    elif not tracker:
        next_action = "Run scripts/task_tracker_build.py to generate outputs/*-task-tracker.csv, then rerun reward eval."
    elif not wi_entries:
        next_action = "Run commands via scripts/ws_run with --work-item-id to capture execution evidence."
    elif bool(proj.frontmatter.get("github_enabled")) and score_gh == 0:
        next_action = "Run github_sync.py to create/sync the GitHub issue mapping."
    else:
        next_action = "Run plan_check.py and add a short QA note to the progress log."

    target = int(fm.get("reward_target") or 0)
    gate_passed = (
        bool(outputs)
        and len(outputs_ok) == len(outputs)
        and bool(evid)
        and len(evid_ok) == len(evid)
        and total >= target
        and truth_pass
    )

    return {
        "work_item_id": wi,
        "title": str(fm.get("title") or ""),
        "status": status,
        "reward_target": target,
        "reward_score": total,
        "gate_passed": gate_passed,
        "components": {
            "acceptance_outputs": score_a,
            "verification": score_v,
            "plan_hygiene": score_h,
            "tracker_dashboard": score_td,
            "lessons": score_l,
            "execution_logs": score_log,
            "github_parity": score_gh,
            "penalties": penalties,
        },
        "evidence": {
            "outputs_declared": outputs,
            "outputs_ok": outputs_ok,
            "verification_declared": evid,
            "verification_ok": evid_ok,
        },
        "next_action": next_action,
        "truth": {
            "status": "pass" if truth_pass else "fail",
            "failures": truth_failures,
            "checks": truth.get("checks") or [],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute behavior-driving reward scores for jobs (updates job plans).")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--work-item-id", help="Evaluate a single WI only")
    parser.add_argument("--out-json", help="Write rewards JSON (default: outputs/rewards.json)")
    parser.add_argument("--out-md", help="Write rewards report (default: outputs/reward-report.md)")
    parser.add_argument("--no-sync", action="store_true", help="Do not run plan_sync after updating reward fields")
    parser.add_argument("--no-dashboard", action="store_true", help="Skip dashboard rebuild after reward eval")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    ts = now_iso()

    results = []
    for ws_dir in list_workstream_dirs(project_root):
        for job_dir in list_job_dirs(ws_dir):
            plan = read_md(job_dir / "plan.md")
            wi = str(plan.frontmatter.get("work_item_id") or "").strip()
            if args.work_item_id and wi != args.work_item_id:
                continue
            results.append((job_dir, compute_job_score(project_root, job_dir)))

    out = [r for _dir, r in results]

    # Update job plans with reward fields (behavior-driving control plane)
    for job_dir, res in results:
        plan_path = job_dir / "plan.md"
        doc = read_md(plan_path)
        doc.frontmatter["reward_last_score"] = int(res["reward_score"])
        doc.frontmatter["reward_last_eval_at"] = ts
        doc.frontmatter["reward_last_next_action"] = str(res["next_action"])
        truth = res.get("truth") or {}
        doc.frontmatter["truth_last_status"] = str(truth.get("status") or "fail")
        doc.frontmatter["truth_last_checked_at"] = ts
        doc.frontmatter["truth_last_failures"] = [str(x) for x in (truth.get("failures") or [])]
        doc.frontmatter["updated_at"] = ts
        # If iteration budget exceeded and gate not passed, auto-block.
        try:
            iteration = int(doc.frontmatter.get("iteration") or 0)
            max_iter = int(doc.frontmatter.get("max_iterations") or 0)
            if max_iter and iteration > max_iter and doc.frontmatter.get("status") not in {"done", "cancelled"}:
                doc.frontmatter["status"] = "blocked"
                doc.body = append_progress_log(
                    doc.body,
                    f"{ts} auto-blocked: iteration {iteration} exceeded max_iterations {max_iter}",
                )
        except Exception:
            pass
        write_md(plan_path, doc)

    outputs_dir = project_root / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)

    out_json = Path(args.out_json).expanduser().resolve() if args.out_json else outputs_dir / "rewards.json"
    out_md = Path(args.out_md).expanduser().resolve() if args.out_md else outputs_dir / "reward-report.md"

    rewards_payload = {
        "schema": "theworkshop.rewards.v1",
        "generated_at": ts,
        "project": str(project_root),
        "jobs": out,
    }
    out_json.write_text(json.dumps(rewards_payload, indent=2) + "\n", encoding="utf-8")

    lines = []
    lines.append("# Reward Report")
    lines.append("")
    lines.append(f"- Generated: {ts}")
    lines.append("")
    lines.append("| Work Item | Status | Score | Target | Gate | Next Action |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for r in out:
        gate = "PASS" if r["gate_passed"] else "FAIL"
        lines.append(
            f"| {r['work_item_id']} | {r['status']} | {r['reward_score']} | {r['reward_target']} | {gate} | {str(r['next_action']).replace('|','\\\\|')} |"
        )
    if not out:
        lines.append("| (none) |  |  |  |  |  |")
    lines.append("")
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Keep the "living plans" tables current (marker blocks in project/workstream plans).
    if not args.no_sync:
        sync_project_plans(project_root, ts=ts)

    # Best-effort monitoring: refresh dashboard so auto-refresh shows updated reward scores/next actions.
    if not args.no_dashboard:
        scripts_dir = Path(__file__).resolve().parent
        try:
            dash = subprocess.run(
                [sys.executable, str(scripts_dir / "dashboard_build.py"), "--project", str(project_root)],
                text=True,
                capture_output=True,
            )
            if dash.returncode != 0:
                print("warning: dashboard_build.py failed (best-effort).", file=sys.stderr)
                if dash.stderr:
                    print(dash.stderr, end="", file=sys.stderr)
        except Exception as e:
            print(f"warning: dashboard rebuild failed (best-effort): {e}", file=sys.stderr)

    print(str(out_md))


if __name__ == "__main__":
    main()
