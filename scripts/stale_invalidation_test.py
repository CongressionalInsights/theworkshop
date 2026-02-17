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
    doc.frontmatter["truth_required_commands"] = []
    doc.body = replace_section(doc.body, "# Objective", ["Produce a stable output file."])
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
        ["- Write `artifacts/verification.md` after validating outputs."],
    )
    job_plan.write_text(join_frontmatter(doc), encoding="utf-8")


def find_job_dir(project_root: Path, wi: str) -> Path:
    matches = list(project_root.glob(f"workstreams/WS-*/jobs/{wi}-*"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one job dir for {wi}, got {len(matches)}")
    return matches[0]


def write_job_artifacts(job_dir: Path, wi: str, text: str) -> None:
    (job_dir / "outputs").mkdir(parents=True, exist_ok=True)
    (job_dir / "artifacts").mkdir(parents=True, exist_ok=True)
    (job_dir / "outputs" / "primary.md").write_text(
        f"# Output {wi}\n\n{text}\n\n<promise>{wi}-DONE</promise>\n",
        encoding="utf-8",
    )
    (job_dir / "artifacts" / "verification.md").write_text(
        f"# Verification\n\nVerified at {now_iso()} for {wi}.\n",
        encoding="utf-8",
    )


def read_frontmatter(path: Path) -> dict:
    return split_frontmatter(path.read_text(encoding="utf-8", errors="ignore")).frontmatter


def main() -> None:
    tmp = tempfile.TemporaryDirectory(prefix="theworkshop-stale-invalidate-")
    base_dir = Path(tmp.name).resolve()

    proj = run(py("project_new.py") + ["--name", "Stale Invalidation Test", "--base-dir", str(base_dir)]).stdout.strip()
    project_root = Path(proj).resolve()
    ws = run(py("workstream_add.py") + ["--project", str(project_root), "--title", "WS"]).stdout.strip()

    wi1 = run(py("job_add.py") + ["--project", str(project_root), "--workstream", ws, "--title", "Upstream", "--stakes", "low"]).stdout.strip()
    wi2 = run(
        py("job_add.py")
        + ["--project", str(project_root), "--workstream", ws, "--title", "Downstream", "--stakes", "low", "--depends-on", wi1]
    ).stdout.strip()

    set_frontmatter(
        project_root / "plan.md",
        agreement_status="agreed",
        agreed_at=now_iso(),
        agreed_notes="stale invalidation test",
        updated_at=now_iso(),
    )

    j1 = find_job_dir(project_root, wi1)
    j2 = find_job_dir(project_root, wi2)
    patch_job_plan(j1 / "plan.md", wi1)
    patch_job_plan(j2 / "plan.md", wi2)

    run(py("job_start.py") + ["--project", str(project_root), "--work-item-id", wi1])
    write_job_artifacts(j1, wi1, "upstream v1")
    run(py("job_complete.py") + ["--project", str(project_root), "--work-item-id", wi1])

    run(py("job_start.py") + ["--project", str(project_root), "--work-item-id", wi2])
    write_job_artifacts(j2, wi2, "downstream built from upstream v1")
    run(py("job_complete.py") + ["--project", str(project_root), "--work-item-id", wi2])

    fm2_done = read_frontmatter(j2 / "plan.md")
    if str(fm2_done.get("status") or "") != "done":
        raise RuntimeError("Expected downstream job to be done before staleness mutation")

    # Mutate upstream output so downstream snapshot becomes stale.
    with (j1 / "outputs" / "primary.md").open("a", encoding="utf-8") as f:
        f.write("\nMutation after downstream completion.\n")

    run(py("invalidate_downstream.py") + ["--project", str(project_root), "--work-item-id", wi1])

    fm2 = read_frontmatter(j2 / "plan.md")
    if str(fm2.get("status") or "") != "blocked":
        raise RuntimeError(f"Expected downstream status=blocked after invalidation, got {fm2.get('status')!r}")
    if str(fm2.get("completed_at") or "").strip():
        raise RuntimeError("Expected downstream completed_at to be cleared after invalidation")
    if str(fm2.get("truth_last_status") or "") != "fail":
        raise RuntimeError("Expected downstream truth_last_status=fail after invalidation")

    body = split_frontmatter((j2 / "plan.md").read_text(encoding="utf-8", errors="ignore")).body
    if "invalidate_downstream" not in body:
        raise RuntimeError("Expected invalidate_downstream progress log entry on downstream job")

    report = json.loads((project_root / "outputs" / "invalidation-report.json").read_text(encoding="utf-8"))
    stale_jobs = report.get("stale_jobs") or []
    if not any(str(item.get("work_item_id") or "") == wi2 for item in stale_jobs if isinstance(item, dict)):
        raise RuntimeError("Expected invalidation-report.json to include downstream stale job")

    print("STALE INVALIDATION TEST PASSED")
    print(str(project_root))
    tmp.cleanup()


if __name__ == "__main__":
    main()
