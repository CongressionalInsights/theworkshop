#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Allow importing TheWorkshop helpers from the scripts directory.
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from twlib import now_iso  # noqa: E402
from twyaml import join_frontmatter, split_frontmatter  # noqa: E402


def run(cmd: list[str], *, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["THEWORKSHOP_NO_OPEN"] = "1"
    env["THEWORKSHOP_NO_MONITOR"] = "1"
    env["THEWORKSHOP_NO_KEYCHAIN"] = "1"
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, capture_output=True, env=env)
    if check and proc.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            f"  cmd={' '.join(cmd)}\n"
            f"  exit={proc.returncode}\n"
            f"  stdout:\n{proc.stdout}\n"
            f"  stderr:\n{proc.stderr}\n"
        )
    return proc


def py(script: str) -> list[str]:
    return [sys.executable, str(SCRIPTS_DIR / script)]


def replace_section(body: str, heading: str, new_lines: list[str]) -> str:
    lines = body.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.strip() == heading.strip():
            start = i
            break
    if start is None:
        return body.rstrip() + "\n\n" + heading + "\n\n" + "\n".join(new_lines).rstrip() + "\n"

    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("# "):
            end = i
            break

    out = lines[: start + 1]
    out.append("")
    out.extend(new_lines)
    out.append("")
    out.extend(lines[end:])
    return "\n".join(out).rstrip() + "\n"


def set_frontmatter(path: Path, **updates) -> None:
    doc = split_frontmatter(path.read_text(encoding="utf-8", errors="ignore"))
    for k, v in updates.items():
        doc.frontmatter[k] = v
    path.write_text(join_frontmatter(doc), encoding="utf-8")


def get_frontmatter(path: Path) -> dict:
    return split_frontmatter(path.read_text(encoding="utf-8", errors="ignore")).frontmatter


def find_job_dir(project_root: Path, wi: str) -> Path:
    matches = list(project_root.glob(f"workstreams/WS-*/jobs/{wi}-*"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected 1 job dir for {wi}, got {len(matches)}: {matches}")
    return matches[0]


def patch_job_plan(job_plan: Path, *, lesson_id: str = "") -> None:
    doc = split_frontmatter(job_plan.read_text(encoding="utf-8", errors="ignore"))
    wi = str(doc.frontmatter.get("work_item_id") or "").strip()
    title = str(doc.frontmatter.get("title") or "").strip()

    doc.body = replace_section(doc.body, "# Objective", [f"Deliver `{title}` with verifiable outputs + evidence so reward gates can pass."])
    doc.body = replace_section(doc.body, "# Outputs", ["- `outputs/primary.md`", "- `artifacts/verification.md`"])
    doc.body = replace_section(
        doc.body,
        "# Acceptance Criteria",
        [
            "- `outputs/primary.md` exists, is non-empty, and contains at least two paragraphs.",
            "- `artifacts/verification.md` exists, is non-empty, and references `outputs/primary.md` explicitly.",
            "- The output includes the completion promise string for this job:",
            f"  - `<promise>{wi}-DONE</promise>`",
        ],
    )
    doc.body = replace_section(
        doc.body,
        "# Verification",
        [
            "- Confirm declared outputs/evidence exist and are non-empty.",
            "- Run `scripts/plan_check.py` for the project and confirm it exits 0.",
            "- Write a short verification note with timestamp into `artifacts/verification.md`.",
        ],
    )
    if lesson_id:
        doc.body = replace_section(doc.body, "# Relevant Lessons Learned", [f"- Applied: {lesson_id}"])
    else:
        doc.body = replace_section(doc.body, "# Relevant Lessons Learned", ["- (none)"])

    job_plan.write_text(join_frontmatter(doc), encoding="utf-8")


def write_job_artifacts(job_dir: Path, *, wi: str) -> None:
    (job_dir / "outputs").mkdir(parents=True, exist_ok=True)
    (job_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (job_dir / "outputs" / "primary.md").write_text(
        "\n".join(
            [
                f"# Output for {wi}",
                "",
                "Paragraph 1: synthetic content for reward gating.",
                "",
                "Paragraph 2: additional content so acceptance criteria are satisfied.",
                "",
                f"Completion: <promise>{wi}-DONE</promise>",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (job_dir / "artifacts" / "verification.md").write_text(
        f"Verified output + evidence present at {now_iso()} for {wi} (outputs/primary.md).\n",
        encoding="utf-8",
    )


def dashboard_stats(project_root: Path) -> dict:
    p = project_root / "outputs" / "dashboard.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a sample multi-workstream scenario to exercise TheWorkshop lifecycle + sync + rewards.")
    parser.add_argument("--keep", action="store_true", help="Keep temp project directory if using --temp")
    parser.add_argument("--temp", action="store_true", help="Use a temp directory (default is repo/_test_runs)")
    parser.add_argument("--base-dir", help="Override base dir (default: <repo>/_test_runs)")
    args = parser.parse_args()

    if args.temp:
        tmp = tempfile.TemporaryDirectory(prefix="theworkshop-sample-")
        base_dir = Path(tmp.name).resolve()
    else:
        tmp = None
        repo_root = SCRIPTS_DIR.parent
        base_dir = Path(args.base_dir).expanduser().resolve() if args.base_dir else (repo_root / "_test_runs")
    base_dir.mkdir(parents=True, exist_ok=True)

    # Create project
    proj = run(py("project_new.py") + ["--name", "TheWorkshop Sample Scenario", "--base-dir", str(base_dir), "--slug", "sample-scenario"]).stdout.strip()
    project_root = Path(proj).resolve()

    # Workstreams
    ws_research = run(py("workstream_add.py") + ["--project", str(project_root), "--title", "Research (Options)"]).stdout.strip()
    ws_memo = run(
        py("workstream_add.py")
        + ["--project", str(project_root), "--title", "Delivery (Memo)", "--depends-on", ws_research]
    ).stdout.strip()

    # Jobs (cross-workstream dependency)
    wi1 = run(
        py("job_add.py")
        + ["--project", str(project_root), "--workstream", ws_research, "--title", "Collect options", "--stakes", "normal"]
    ).stdout.strip()
    wi2 = run(
        py("job_add.py")
        + ["--project", str(project_root), "--workstream", ws_research, "--title", "Score + shortlist", "--stakes", "normal", "--depends-on", wi1]
    ).stdout.strip()
    wi3 = run(
        py("job_add.py")
        + [
            "--project",
            str(project_root),
            "--workstream",
            ws_memo,
            "--title",
            "Write final memo",
            "--stakes",
            "high",
            "--depends-on",
            wi2,
        ]
    ).stdout.strip()

    # Agree so lifecycle scripts can run.
    set_frontmatter(
        project_root / "plan.md",
        agreement_status="agreed",
        agreed_at=now_iso(),
        agreed_notes="sample scenario auto-agree",
        status="in_progress",
        updated_at=now_iso(),
    )

    # Patch job plans to remove placeholders (required for reward targets).
    patch_job_plan(find_job_dir(project_root, wi1) / "plan.md")
    patch_job_plan(find_job_dir(project_root, wi2) / "plan.md")
    patch_job_plan(find_job_dir(project_root, wi3) / "plan.md")

    # Start WI-1; create artifacts; add a logged validation command; complete.
    run(py("job_start.py") + ["--project", str(project_root), "--work-item-id", wi1])
    write_job_artifacts(find_job_dir(project_root, wi1), wi=wi1)
    run(
        py("ws_run")
        + ["--project", str(project_root), "--label", "plan_check", "--work-item-id", wi1, "--phase", "validate", "--", sys.executable, str(SCRIPTS_DIR / "plan_check.py"), "--project", str(project_root)]
    )
    run(py("job_complete.py") + ["--project", str(project_root), "--work-item-id", wi1])

    # Start WI-2; intentionally fail completion once (no artifacts).
    run(py("job_start.py") + ["--project", str(project_root), "--work-item-id", wi2])
    fail_proc = run(py("job_complete.py") + ["--project", str(project_root), "--work-item-id", wi2], check=False)
    if fail_proc.returncode == 0:
        raise RuntimeError("Expected WI-2 completion to fail when outputs/evidence are missing, but it succeeded.")
    fm2 = get_frontmatter(find_job_dir(project_root, wi2) / "plan.md")
    if str(fm2.get("status") or "") != "in_progress":
        raise RuntimeError(f"Expected WI-2 to revert to in_progress, got: {fm2.get('status')!r}")

    # Capture a lesson about reward gating and link it to WI-2.
    run(
        py("lessons_capture.py")
        + [
            "--project",
            str(project_root),
            "--tags",
            "rewards,verification",
            "--linked",
            wi2,
            "--context",
            "Attempted to complete a job without generating declared outputs/evidence.",
            "--worked",
            "Reward-gated completion reverted status and forced us to create evidence.",
            "--failed",
            "Skipping artifacts caused predictable gate failure.",
            "--recommendation",
            "Create outputs + verification evidence before calling job_complete.",
        ]
    )
    # Read last lesson id for linkage.
    lessons_md = project_root / "notes" / "lessons-learned.md"
    lesson_id = ""
    for ln in lessons_md.read_text(encoding="utf-8", errors="ignore").splitlines():
        if ln.startswith("## LL-"):
            lesson_id = ln.split()[1].strip()
    if lesson_id:
        patch_job_plan(find_job_dir(project_root, wi2) / "plan.md", lesson_id=lesson_id)

    # Fix WI-2 and complete with cascade (should auto-complete WS_research when eligible).
    write_job_artifacts(find_job_dir(project_root, wi2), wi=wi2)
    run(
        py("ws_run")
        + ["--project", str(project_root), "--label", "plan_check", "--work-item-id", wi2, "--phase", "validate", "--", sys.executable, str(SCRIPTS_DIR / "plan_check.py"), "--project", str(project_root)]
    )
    run(py("job_complete.py") + ["--project", str(project_root), "--work-item-id", wi2, "--cascade"])

    # Start WI-3; force iteration budget exceed -> reward_eval auto-block; then "decision" to increase max_iterations and resume.
    run(py("job_start.py") + ["--project", str(project_root), "--work-item-id", wi3])
    job3_plan = find_job_dir(project_root, wi3) / "plan.md"
    fm3 = get_frontmatter(job3_plan)
    max_iter = int(fm3.get("max_iterations") or 0) or 3
    set_frontmatter(job3_plan, iteration=max_iter + 1, updated_at=now_iso())
    run(py("reward_eval.py") + ["--project", str(project_root), "--work-item-id", wi3])
    fm3b = get_frontmatter(job3_plan)
    if str(fm3b.get("status") or "") != "blocked":
        raise RuntimeError(f"Expected WI-3 to be auto-blocked by reward_eval, got: {fm3b.get('status')!r}")

    # Simulate decision to increase budget and resume.
    set_frontmatter(job3_plan, max_iterations=max_iter + 10, updated_at=now_iso())
    run(py("job_start.py") + ["--project", str(project_root), "--work-item-id", wi3])
    write_job_artifacts(find_job_dir(project_root, wi3), wi=wi3)
    run(
        py("ws_run")
        + ["--project", str(project_root), "--label", "plan_check", "--work-item-id", wi3, "--phase", "validate", "--", sys.executable, str(SCRIPTS_DIR / "plan_check.py"), "--project", str(project_root)]
    )
    run(py("job_complete.py") + ["--project", str(project_root), "--work-item-id", wi3, "--cascade"])

    # Final gate + dashboard refresh
    run(py("plan_check.py") + ["--project", str(project_root)])
    run(py("dashboard_build.py") + ["--project", str(project_root)])

    payload = dashboard_stats(project_root)
    stats = (payload.get("stats") or {}).get("jobs_status") or {}
    tokens = payload.get("tokens") or {}
    for key in (
        "cost_source",
        "cost_confidence",
        "estimated_session_cost_usd",
        "estimated_project_cost_usd",
        "billing_mode",
        "billing_confidence",
        "billing_reason",
        "billed_session_cost_usd",
        "billed_project_cost_usd",
        "api_equivalent_session_cost_usd",
        "api_equivalent_project_cost_usd",
        "display_cost_primary_label",
        "display_cost_secondary_label",
        "project_cost_baseline_tokens",
        "project_cost_delta_tokens",
        "rate_model_key",
        "rate_resolution",
        "cost_breakdown",
        "by_work_item",
        "unattributed_cost_usd",
    ):
        if key not in tokens:
            raise RuntimeError(f"Expected dashboard tokens payload to include {key!r}")

    # HTML auto-refresh markers + generated timestamp should be present.
    html_path = project_root / "outputs" / "dashboard.html"
    html = html_path.read_text(encoding="utf-8", errors="ignore")
    gen = str(payload.get("generated_at") or "")
    if gen and gen not in html:
        raise RuntimeError("Expected dashboard.html to include generated_at timestamp from dashboard.json.")
    if "twRefreshToggle" not in html or "theworkshop.autorefresh.enabled" not in html:
        raise RuntimeError("Expected dashboard.html to include TheWorkshop auto-refresh controller markers.")

    print(str(project_root))
    print(str(project_root / "outputs" / "dashboard.html"))
    print(f"jobs_status={stats}")

    if tmp is not None and not args.keep:
        tmp.cleanup()


if __name__ == "__main__":
    main()
