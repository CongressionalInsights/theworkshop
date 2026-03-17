#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from twlib import now_iso
from twyaml import join_frontmatter, split_frontmatter


SCRIPTS_DIR = Path(__file__).resolve().parent


def py(script: str) -> list[str]:
    return [sys.executable, str(SCRIPTS_DIR / script)]


def run(cmd: list[str], *, env: dict[str, str], check: bool = True) -> subprocess.CompletedProcess[str]:
    merged = dict(os.environ)
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
    for key, value in updates.items():
        doc.frontmatter[key] = value
    path.write_text(join_frontmatter(doc), encoding="utf-8")


def browser_hits(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="theworkshop-job-start-open-") as td:
        base_dir = Path(td).resolve()
        browser_log = base_dir / "browser.log"
        browser_cmd = base_dir / "browser.sh"
        browser_cmd.write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' \"$1\" >> \"$BROWSER_LOG\"\n"
            "exit 0\n",
            encoding="utf-8",
        )
        browser_cmd.chmod(browser_cmd.stat().st_mode | stat.S_IXUSR)

        env = {
            "THEWORKSHOP_NO_KEYCHAIN": "1",
            "THEWORKSHOP_NO_MONITOR": "1",
            "THEWORKSHOP_SESSION_ID": "job-start-open-test",
            "BROWSER": str(browser_cmd),
            "BROWSER_LOG": str(browser_log),
        }

        project_root = Path(
            run(py("project_new.py") + ["--name", "Job Start Open Behavior", "--base-dir", str(base_dir)], env=env).stdout.strip()
        ).resolve()
        ws_id = run(py("workstream_add.py") + ["--project", str(project_root), "--title", "WS"], env=env).stdout.strip()
        wi = run(
            py("job_add.py") + ["--project", str(project_root), "--workstream", ws_id, "--title", "Job"],
            env=env,
        ).stdout.strip()

        set_frontmatter(
            project_root / "plan.md",
            agreement_status="agreed",
            agreed_at=now_iso(),
            agreed_notes="open behavior test",
            status="in_progress",
        )

        run(py("job_start.py") + ["--project", str(project_root), "--work-item-id", wi], env=env)
        first_hits = browser_hits(browser_log)
        if len(first_hits) != 1:
            raise RuntimeError(f"Expected one browser open from job_start, got {first_hits}")

        run(
            py("project_close.py")
            + ["--project", str(project_root), "--status", "cancelled", "--reason", "terminal open behavior test"],
            env=env,
        )
        second_hits = browser_hits(browser_log)
        if len(second_hits) != 1:
            raise RuntimeError(f"Expected no new browser open on terminal closeout, got {second_hits}")

        runtime_state = json.loads((project_root / "tmp" / "monitor-runtime.json").read_text(encoding="utf-8"))
        if str(runtime_state.get("cleanup_status") or "") != "pruned":
            raise RuntimeError(f"Expected cleanup_status=pruned after terminal closeout: {runtime_state}")

    print("JOB START TERMINAL OPEN BEHAVIOR TEST PASSED")


if __name__ == "__main__":
    main()
