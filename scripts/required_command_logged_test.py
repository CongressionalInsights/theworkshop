#!/usr/bin/env python3
from __future__ import annotations

import json
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
    doc.frontmatter["truth_required_commands"] = ["must-run-cmd"]
    doc.body = replace_section(doc.body, "# Objective", ["Generate one output and verification evidence."])
    doc.body = replace_section(doc.body, "# Outputs", ["- `outputs/primary.md`"])
    doc.body = replace_section(
        doc.body,
        "# Acceptance Criteria",
        [
            "- `outputs/primary.md` exists and is non-empty.",
            f"- Includes completion token `<promise>{wi}-DONE</promise>`.",
        ],
    )
    doc.body = replace_section(
        doc.body,
        "# Verification",
        [
            "- Validate output exists and is non-empty.",
            "- Record verification note in `artifacts/verification.md`.",
        ],
    )
    job_plan.write_text(join_frontmatter(doc), encoding="utf-8")


def find_job_dir(project_root: Path, wi: str) -> Path:
    matches = list(project_root.glob(f"workstreams/WS-*/jobs/{wi}-*"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one job dir for {wi}, got {len(matches)}")
    return matches[0]


def read_truth(project_root: Path, wi: str) -> dict:
    payload = json.loads((project_root / "outputs" / "truth-report.json").read_text(encoding="utf-8"))
    for item in payload.get("jobs", []):
        if str(item.get("work_item_id") or "") == wi:
            return item
    raise RuntimeError(f"Work item {wi} not found in truth-report.json")


def read_frontmatter(path: Path) -> dict:
    return split_frontmatter(path.read_text(encoding="utf-8", errors="ignore")).frontmatter


def main() -> None:
    tmp = tempfile.TemporaryDirectory(prefix="theworkshop-required-cmd-")
    base_dir = Path(tmp.name).resolve()

    proj = run(py("project_new.py") + ["--name", "Required Command Test", "--base-dir", str(base_dir)]).stdout.strip()
    project_root = Path(proj).resolve()
    ws = run(py("workstream_add.py") + ["--project", str(project_root), "--title", "WS"]).stdout.strip()
    wi = run(py("job_add.py") + ["--project", str(project_root), "--workstream", ws, "--title", "Command Gate", "--stakes", "low"]).stdout.strip()

    set_frontmatter(
        project_root / "plan.md",
        agreement_status="agreed",
        agreed_at=now_iso(),
        agreed_notes="required command test",
        updated_at=now_iso(),
    )

    job_dir = find_job_dir(project_root, wi)
    patch_job_plan(job_dir / "plan.md", wi)
    (job_dir / "outputs").mkdir(parents=True, exist_ok=True)
    (job_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (job_dir / "outputs" / "primary.md").write_text(
        f"# Output\n\nSome content.\n\n<promise>{wi}-DONE</promise>\n",
        encoding="utf-8",
    )
    (job_dir / "artifacts" / "verification.md").write_text(
        "# Verification\n\nOutput exists and is non-empty.\n",
        encoding="utf-8",
    )

    run(py("job_start.py") + ["--project", str(project_root), "--work-item-id", wi])

    run(py("truth_eval.py") + ["--project", str(project_root), "--work-item-id", wi])
    first_truth = read_truth(project_root, wi)
    if str(first_truth.get("truth_status") or "") != "fail":
        raise RuntimeError("Expected truth status fail before required command is logged")

    run(
        py("ws_run")
        + [
            "--project",
            str(project_root),
            "--label",
            "must-run-cmd",
            "--work-item-id",
            wi,
            "--phase",
            "validate",
            "--",
            "echo",
            "ok",
        ]
    )

    run(py("truth_eval.py") + ["--project", str(project_root), "--work-item-id", wi])
    second_truth = read_truth(project_root, wi)
    if str(second_truth.get("truth_status") or "") != "pass":
        raise RuntimeError(f"Expected truth status pass after required command logging, got {second_truth.get('truth_status')!r}")

    run(py("job_complete.py") + ["--project", str(project_root), "--work-item-id", wi])
    fm = read_frontmatter(job_dir / "plan.md")
    if str(fm.get("status") or "") != "done":
        raise RuntimeError("Expected job status done after truth and reward gates pass")

    print("REQUIRED COMMAND LOGGED TEST PASSED")
    print(str(project_root))
    tmp.cleanup()


if __name__ == "__main__":
    main()
