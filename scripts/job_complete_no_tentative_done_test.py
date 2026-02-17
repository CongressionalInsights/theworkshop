#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from twlib import now_iso  # noqa: E402
from twyaml import join_frontmatter, split_frontmatter  # noqa: E402


def py(script: str) -> list[str]:
    return [sys.executable, str(SCRIPTS_DIR / script)]


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["THEWORKSHOP_NO_OPEN"] = "1"
    env["THEWORKSHOP_NO_MONITOR"] = "1"
    env["THEWORKSHOP_NO_KEYCHAIN"] = "1"
    proc = subprocess.run(cmd, text=True, capture_output=True, env=env)
    if check and proc.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            f"  cmd={' '.join(cmd)}\n"
            f"  exit={proc.returncode}\n"
            f"  stdout:\n{proc.stdout}\n"
            f"  stderr:\n{proc.stderr}\n"
        )
    return proc


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


def patch_job_plan(job_plan: Path, wi: str) -> None:
    doc = split_frontmatter(job_plan.read_text(encoding="utf-8", errors="ignore"))
    doc.frontmatter["outputs"] = ["outputs/primary.md"]
    doc.frontmatter["verification_evidence"] = ["artifacts/verification.md"]
    doc.body = replace_section(doc.body, "# Objective", ["Create one output and verification evidence."])
    doc.body = replace_section(doc.body, "# Outputs", ["- `outputs/primary.md`"])
    doc.body = replace_section(
        doc.body,
        "# Acceptance Criteria",
        [
            "- `outputs/primary.md` exists and is non-empty.",
            f"- Contains `<promise>{wi}-DONE</promise>`.",
        ],
    )
    doc.body = replace_section(
        doc.body,
        "# Verification",
        ["- Write verification evidence to `artifacts/verification.md`."],
    )
    job_plan.write_text(join_frontmatter(doc), encoding="utf-8")


def read_doc(path: Path):
    return split_frontmatter(path.read_text(encoding="utf-8", errors="ignore"))


def find_job_plan(project_root: Path, wi: str) -> Path:
    matches = list(project_root.glob(f"workstreams/WS-*/jobs/{wi}-*/plan.md"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one job plan for {wi}, got {len(matches)}")
    return matches[0]


def main() -> None:
    tmp = tempfile.TemporaryDirectory(prefix="theworkshop-no-tentative-done-")
    base_dir = Path(tmp.name).resolve()

    proj = run(py("project_new.py") + ["--name", "No Tentative Done Test", "--base-dir", str(base_dir)]).stdout.strip()
    project_root = Path(proj).resolve()
    ws = run(py("workstream_add.py") + ["--project", str(project_root), "--title", "WS"]).stdout.strip()
    wi = run(py("job_add.py") + ["--project", str(project_root), "--workstream", ws, "--title", "Failing Job", "--stakes", "low"]).stdout.strip()

    set_frontmatter(
        project_root / "plan.md",
        agreement_status="agreed",
        agreed_at=now_iso(),
        agreed_notes="job complete no tentative done test",
        updated_at=now_iso(),
    )

    job_plan = find_job_plan(project_root, wi)
    patch_job_plan(job_plan, wi)

    run(py("job_start.py") + ["--project", str(project_root), "--work-item-id", wi])

    failed = run(py("job_complete.py") + ["--project", str(project_root), "--work-item-id", wi], check=False)
    if failed.returncode == 0:
        raise RuntimeError("Expected job_complete to fail when required outputs/evidence are missing")

    doc = read_doc(job_plan)
    status = str(doc.frontmatter.get("status") or "")
    if status == "done":
        raise RuntimeError("Job should not be marked done when completion gate fails")
    if str(doc.frontmatter.get("completed_at") or "").strip():
        raise RuntimeError("completed_at should be empty after failed completion")

    text = doc.body
    if "gate PASSED" in text:
        raise RuntimeError("Progress log should not contain gate PASSED for failed completion")
    if "FAILED gate" not in text:
        raise RuntimeError("Progress log should record FAILED gate on completion failure")

    print("JOB COMPLETE NO TENTATIVE DONE TEST PASSED")
    print(str(project_root))
    tmp.cleanup()


if __name__ == "__main__":
    main()
