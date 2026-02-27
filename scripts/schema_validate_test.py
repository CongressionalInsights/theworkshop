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
    for key, value in updates.items():
        doc.frontmatter[key] = value
    path.write_text(join_frontmatter(doc), encoding="utf-8")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="theworkshop-schema-") as td:
        base = Path(td).resolve()
        project_root = Path(
            run(py("project_new.py") + ["--name", "Schema Validate Test", "--base-dir", str(base)]).stdout.strip()
        ).resolve()
        ws_id = run(py("workstream_add.py") + ["--project", str(project_root), "--title", "WS"]).stdout.strip()
        wi = run(py("job_add.py") + ["--project", str(project_root), "--workstream", ws_id, "--title", "Job"]).stdout.strip()

        set_frontmatter(
            project_root / "plan.md",
            agreement_status="agreed",
            agreed_at=now_iso(),
            agreed_notes="schema validate test",
            status="in_progress",
        )

        run(py("orchestrate_plan.py") + ["--project", str(project_root)])
        run(py("reward_eval.py") + ["--project", str(project_root), "--no-dashboard"])
        run(py("truth_eval.py") + ["--project", str(project_root), "--no-dashboard"])
        run(py("dashboard_build.py") + ["--project", str(project_root)])
        run(py("dispatch_orchestration.py") + ["--project", str(project_root), "--dry-run"])

        run(py("schema_validate.py") + ["--project", str(project_root), "--strict-missing"])

        out = project_root / "outputs" / "schema-validation.json"
        if not out.exists():
            raise RuntimeError(f"Missing schema validation output: {out}")

        print("SCHEMA VALIDATE TEST PASSED")


if __name__ == "__main__":
    main()
