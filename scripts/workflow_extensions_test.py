#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

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


def set_frontmatter(path: Path, **updates) -> None:
    doc = split_frontmatter(path.read_text(encoding="utf-8", errors="ignore"))
    for k, v in updates.items():
        doc.frontmatter[k] = v
    path.write_text(join_frontmatter(doc), encoding="utf-8")


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Test TheWorkshop extensions: discuss, verify-work, health, quick.")
    parser.add_argument("--keep", action="store_true", help="Keep temporary directory")
    args = parser.parse_args()

    tmp = tempfile.TemporaryDirectory(prefix="theworkshop-ext-")
    base_dir = Path(tmp.name).resolve()

    # Seed project + one WS/WI.
    proj = run(py("project_new.py") + ["--name", "Extensions Test", "--base-dir", str(base_dir)]).stdout.strip()
    project_root = Path(proj).resolve()
    ws_id = run(py("workstream_add.py") + ["--project", str(project_root), "--title", "Main Stream"]).stdout.strip()
    wi = run(py("job_add.py") + ["--project", str(project_root), "--workstream", ws_id, "--title", "Main Job"]).stdout.strip()

    # Prepare agreement and concrete acceptance criteria (for verify-work test extraction).
    set_frontmatter(
        project_root / "plan.md",
        agreement_status="agreed",
        agreed_notes="test",
        status="in_progress",
    )
    job_plan = next(project_root.glob("workstreams/WS-*/jobs/WI-*/plan.md"))
    job_doc = split_frontmatter(job_plan.read_text(encoding="utf-8", errors="ignore"))
    job_doc.body = replace_section(
        job_doc.body,
        "# Acceptance Criteria",
        [
            "- Output includes a concise summary section.",
            "- Evidence file references the generated output path.",
        ],
    )
    job_doc.body = replace_section(
        job_doc.body,
        "# Verification",
        [
            "- Confirm output and evidence files exist.",
            "- Verify summary section is present.",
        ],
    )
    job_plan.write_text(join_frontmatter(job_doc), encoding="utf-8")

    # discuss: create context + mark required.
    c1 = run(
        py("discuss.py")
        + [
            "--project",
            str(project_root),
            "--work-item-id",
            wi,
            "--decision",
            "Use concise executive summary format",
            "--defer",
            "Add appendix in later iteration",
            "--required",
            "--no-interactive",
        ]
    ).stdout.strip()
    context_path = project_root / c1
    if not context_path.exists():
        raise RuntimeError("Expected discuss.py to create context file")

    # discuss rerun merge behavior.
    run(
        py("discuss.py")
        + [
            "--project",
            str(project_root),
            "--work-item-id",
            wi,
            "--decision",
            "Keep source citations in bullet form",
            "--no-interactive",
        ]
    )
    ctx = split_frontmatter(context_path.read_text(encoding="utf-8", errors="ignore"))
    locked = ctx.frontmatter.get("locked_decisions") or []
    if len(locked) < 2:
        raise RuntimeError("Expected discuss merge behavior to retain + append locked decisions")

    # job_start should pass context gate now.
    run(py("job_start.py") + ["--project", str(project_root), "--work-item-id", wi, "--no-open", "--no-monitor"])

    # verify-work resumable flow.
    run(
        py("verify_work.py")
        + [
            "--project",
            str(project_root),
            "--work-item-id",
            wi,
            "--responses",
            "pass",
            "--non-interactive",
            "--no-dashboard",
        ]
    )
    # Resume active run and fail remaining test.
    uat_out = run(
        py("verify_work.py")
        + ["--project", str(project_root), "--work-item-id", wi, "--responses", "fail:missing evidence link", "--no-dashboard"]
    ).stdout

    uat_lines = [ln.strip() for ln in uat_out.splitlines() if ln.strip()]
    if not uat_lines:
        raise RuntimeError("verify_work.py did not emit any output")
    uat_md = uat_lines[-1]

    uat_path = project_root / uat_md
    if not uat_path.exists():
        raise RuntimeError("Expected verify_work.py to write UAT markdown artifact")

    # Ensure verify-work fed completion gate fields.
    job_doc = split_frontmatter(job_plan.read_text(encoding="utf-8", errors="ignore"))
    if str(job_doc.frontmatter.get("uat_last_status") or "") != "fail":
        raise RuntimeError("Expected uat_last_status=fail after failed verify-work response")
    if not (job_doc.frontmatter.get("uat_open_issues") or []):
        raise RuntimeError("Expected uat_open_issues to be populated after failed verify-work response")

    # health report + repair path.
    h1 = run(py("health.py") + ["--project", str(project_root)], check=False)
    if "outputs/health.json" not in (h1.stdout + h1.stderr):
        raise RuntimeError("health.py should report outputs/health.json path")

    h2 = run(py("health.py") + ["--project", str(project_root), "--repair"], check=False)
    if "outputs/health.json" not in (h2.stdout + h2.stderr):
        raise RuntimeError("health.py --repair should report outputs/health.json path")
    if not (project_root / "outputs" / "health.json").exists():
        raise RuntimeError("Expected outputs/health.json to exist after health runs")

    # quick path should create isolated quick artifacts and keep dashboard path valid.
    qsum = run(
        py("quick.py")
        + [
            "--project",
            str(project_root),
            "--title",
            "Generate quick note",
            "--command",
            "echo quick-run",
            "--no-open",
        ]
    ).stdout.strip()
    summary_path = project_root / qsum
    if not summary_path.exists():
        raise RuntimeError("Expected quick.py to create summary artifact")
    if "quick" not in qsum:
        raise RuntimeError("Expected quick summary path to live under quick/")

    print("WORKFLOW EXTENSIONS TEST PASSED")
    print(f"Project root: {project_root}")

    if not args.keep:
        tmp.cleanup()


if __name__ == "__main__":
    main()
