#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from twyaml import split_frontmatter  # noqa: E402


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


def find_job_plan(project_root: Path, wi: str) -> Path:
    matches = list(project_root.glob(f"workstreams/WS-*/jobs/{wi}-*/plan.md"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one job plan for {wi}, got {len(matches)}")
    return matches[0]


def main() -> None:
    tmp = tempfile.TemporaryDirectory(prefix="theworkshop-job-profile-")
    base_dir = Path(tmp.name).resolve()

    project_root = Path(
        run(py("project_new.py") + ["--name", "Job Profile Test", "--base-dir", str(base_dir)]).stdout.strip()
    ).resolve()
    ws = run(py("workstream_add.py") + ["--project", str(project_root), "--title", "Profiles"]).stdout.strip()

    wi_attr = run(
        py("job_add.py")
        + [
            "--project",
            str(project_root),
            "--workstream",
            ws,
            "--title",
            "Attribution Sweep",
            "--job-profile",
            "investigation_attribution",
        ]
    ).stdout.strip()
    wi_identity = run(
        py("job_add.py")
        + [
            "--project",
            str(project_root),
            "--workstream",
            ws,
            "--title",
            "Identity Match",
            "--job-profile",
            "identity_resolution",
        ]
    ).stdout.strip()

    attr_doc = split_frontmatter(find_job_plan(project_root, wi_attr).read_text(encoding="utf-8", errors="ignore"))
    if str(attr_doc.frontmatter.get("job_profile") or "") != "investigation_attribution":
        raise RuntimeError("Expected job_profile=investigation_attribution")
    outputs = attr_doc.frontmatter.get("outputs") or []
    if "outputs/candidate_ranked.md" not in outputs or "outputs/deed_hits.csv" not in outputs:
        raise RuntimeError("Investigation profile should seed ranked candidates + deed outputs")
    if "attributable matches" not in attr_doc.body.lower() or "excluded collisions" not in attr_doc.body.lower():
        raise RuntimeError("Investigation profile body should include attribution vs collision acceptance language")

    id_doc = split_frontmatter(find_job_plan(project_root, wi_identity).read_text(encoding="utf-8", errors="ignore"))
    if str(id_doc.frontmatter.get("job_profile") or "") != "identity_resolution":
        raise RuntimeError("Expected job_profile=identity_resolution")
    id_outputs = id_doc.frontmatter.get("outputs") or []
    if "outputs/name-variant-normalization.md" not in id_outputs or "outputs/timeline-overlap.md" not in id_outputs:
        raise RuntimeError("Identity profile should seed variant normalization + timeline outputs")
    if "same-entity" not in id_doc.body.lower() and "same/not-same" not in id_doc.body.lower():
        raise RuntimeError("Identity profile body should mention same-entity determination criteria")

    print("JOB PROFILE TEST PASSED")
    print(str(project_root))
    tmp.cleanup()


if __name__ == "__main__":
    main()
