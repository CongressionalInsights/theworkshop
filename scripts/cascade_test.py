#!/usr/bin/env python3
from __future__ import annotations

import argparse
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


def find_single(glob_iter) -> Path:
    items = list(glob_iter)
    if len(items) != 1:
        raise RuntimeError(f"Expected exactly 1 match, got {len(items)}: {items}")
    return items[0]


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


def update_job_plan_body(job_plan: Path) -> None:
    doc = split_frontmatter(job_plan.read_text(encoding="utf-8", errors="ignore"))
    body = doc.body
    body = replace_section(
        body,
        "# Acceptance Criteria",
        [
            "- `outputs/primary.md` exists, is non-empty, and describes the intended deliverable in full sentences (not placeholders).",
            "- `artifacts/verification.md` exists, is non-empty, and references `outputs/primary.md` explicitly.",
        ],
    )
    body = replace_section(
        body,
        "# Verification",
        [
            "- Confirm `outputs/primary.md` exists and contains at least two lines of content.",
            "- Confirm `artifacts/verification.md` exists and includes a timestamp and the output filename.",
            "- Run `scripts/plan_check.py` and confirm it exits 0.",
        ],
    )
    doc.body = body
    job_plan.write_text(join_frontmatter(doc), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Test job_complete --cascade (auto-complete workstream + project).")
    parser.add_argument("--keep", action="store_true", help="Keep the temp project directory")
    args = parser.parse_args()

    tmp = tempfile.TemporaryDirectory(prefix="theworkshop-cascade-")
    base_dir = Path(tmp.name).resolve()
    base_dir.mkdir(parents=True, exist_ok=True)
    print(f"[1] Base dir: {base_dir}")

    proj = run(py("project_new.py") + ["--name", "TheWorkshop Cascade Test", "--base-dir", str(base_dir)]).stdout.strip()
    project_root = Path(proj).resolve()
    print(f"[2] Project: {project_root}")

    ws_id = run(py("workstream_add.py") + ["--project", str(project_root), "--title", "Only Workstream"]).stdout.strip()
    wi_id = run(
        py("job_add.py") + ["--project", str(project_root), "--workstream", ws_id, "--title", "Only Job", "--stakes", "low"]
    ).stdout.strip()
    print(f"[3] WS/WI: {ws_id} / {wi_id}")

    # Agree so lifecycle scripts can execute.
    set_frontmatter(
        project_root / "plan.md",
        agreement_status="agreed",
        agreed_at=now_iso(),
        agreed_notes="cascade test auto-agree",
        status="in_progress",
        updated_at=now_iso(),
    )

    job_dir = find_single(project_root.glob("workstreams/WS-*/jobs/WI-*"))
    job_plan = job_dir / "plan.md"
    update_job_plan_body(job_plan)

    # Create declared output + evidence so reward gates can pass.
    (job_dir / "outputs").mkdir(parents=True, exist_ok=True)
    (job_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (job_dir / "outputs" / "primary.md").write_text("This is a synthetic output.\nIt has more than one line.\n", encoding="utf-8")
    (job_dir / "artifacts" / "verification.md").write_text(f"Verified at {now_iso()} for outputs/primary.md\n", encoding="utf-8")

    # Start and complete with cascade.
    run(py("job_start.py") + ["--project", str(project_root), "--work-item-id", wi_id])
    run(py("job_complete.py") + ["--project", str(project_root), "--work-item-id", wi_id, "--cascade"])

    # Validate status transitions.
    ws_plan = find_single(project_root.glob("workstreams/WS-*/plan.md"))
    ws_doc = split_frontmatter(ws_plan.read_text(encoding="utf-8", errors="ignore"))
    if str(ws_doc.frontmatter.get("status") or "") != "done":
        raise RuntimeError(f"Expected workstream status=done, got: {ws_doc.frontmatter.get('status')!r}")

    proj_doc = split_frontmatter((project_root / "plan.md").read_text(encoding="utf-8", errors="ignore"))
    if str(proj_doc.frontmatter.get("status") or "") != "done":
        raise RuntimeError(f"Expected project status=done, got: {proj_doc.frontmatter.get('status')!r}")

    # Full consistency gate.
    run(py("plan_check.py") + ["--project", str(project_root)])
    print("")
    print("CASCADE TEST PASSED")
    print(f"Project root: {project_root}")

    if not args.keep:
        tmp.cleanup()


if __name__ == "__main__":
    main()
