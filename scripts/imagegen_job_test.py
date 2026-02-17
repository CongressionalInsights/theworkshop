#!/usr/bin/env python3
from __future__ import annotations

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


def py(script: str) -> list[str]:
    return [sys.executable, str(SCRIPTS_DIR / script)]


def run(cmd: list[str], *, env: dict | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    merged = dict(os.environ)
    merged["THEWORKSHOP_NO_OPEN"] = "1"
    merged["THEWORKSHOP_NO_MONITOR"] = "1"
    merged["THEWORKSHOP_NO_KEYCHAIN"] = "1"
    if env:
        merged.update(env)
    proc = subprocess.run(cmd, text=True, capture_output=True, env=merged)
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


def main() -> None:
    tmp = tempfile.TemporaryDirectory(prefix="theworkshop-imagegen-job-test-")
    base_dir = Path(tmp.name).resolve()

    proj = run(py("project_new.py") + ["--name", "Imagegen Dry Run Test", "--base-dir", str(base_dir)]).stdout.strip()
    project_root = Path(proj).resolve()
    ws_id = run(py("workstream_add.py") + ["--project", str(project_root), "--title", "Visual Assets"]).stdout.strip()
    wi_id = run(
        py("job_add.py")
        + ["--project", str(project_root), "--workstream", ws_id, "--title", "Generate images", "--stakes", "normal"]
    ).stdout.strip()

    set_frontmatter(
        project_root / "plan.md",
        agreement_status="agreed",
        agreed_at=now_iso(),
        agreed_notes="imagegen dry-run test",
        updated_at=now_iso(),
    )

    job_dir = next(project_root.glob(f"workstreams/WS-*/jobs/{wi_id}-*"))
    prompts = job_dir / "artifacts" / "prompts.jsonl"
    prompts.parent.mkdir(parents=True, exist_ok=True)
    prompts.write_text(
        "\n".join(
            [
                '{"out":"cover.png","prompt":"A clean workshop cover illustration","size":"1024x1536"}',
                '{"out":"diagram-loop.png","prompt":"A loop diagram with large labels","size":"1536x1024"}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    proc = run(
        py("imagegen_job.py")
        + ["--project", str(project_root), "--work-item-id", wi_id, "--dry-run"],
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "imagegen_job dry-run failed unexpectedly:\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}\n"
        )
    if "dry_run=1" not in (proc.stdout or ""):
        raise RuntimeError(f"Expected dry_run marker in output, got:\n{proc.stdout}")
    if "prompt_out_paths:" not in (proc.stdout or ""):
        raise RuntimeError(f"Expected prompt_out_paths marker in output, got:\n{proc.stdout}")

    print("IMAGEGEN JOB DRY-RUN TEST PASSED")
    print(str(project_root))
    tmp.cleanup()


if __name__ == "__main__":
    main()
