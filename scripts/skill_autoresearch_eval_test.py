#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent


def run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    merged = dict(os.environ)
    merged["THEWORKSHOP_NO_OPEN"] = "1"
    merged["THEWORKSHOP_NO_MONITOR"] = "1"
    merged["THEWORKSHOP_NO_KEYCHAIN"] = "1"
    if env:
        merged.update(env)
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, capture_output=True, env=merged)
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


def git(repo: Path, *args: str) -> None:
    run(["git", *args], cwd=repo)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="theworkshop-skill-autoresearch-") as td:
        root = Path(td).resolve()
        repo = root / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        git(repo, "init")
        git(repo, "config", "user.email", "tests@example.com")
        git(repo, "config", "user.name", "TheWorkshop Tests")

        (repo / "allowed.txt").write_text("baseline\n", encoding="utf-8")
        (repo / "blocked.txt").write_text("baseline\n", encoding="utf-8")
        pack = root / "pack.json"
        pack.write_text(
            json.dumps(
                {
                    "name": "unit-pack",
                    "allowed_globs": ["allowed.txt"],
                    "scope_policy": {
                        "reject_unauthorized": True,
                        "require_clean_worktree": True,
                    },
                    "benchmarks": [
                        {
                            "id": "pass",
                            "command": "python3 -c \"print('ok')\"",
                            "weight": 1,
                            "timeout_sec": 10,
                        }
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        git(repo, "add", "allowed.txt", "blocked.txt")
        git(repo, "commit", "-m", "baseline")

        results_tsv = root / "state" / "autoresearch" / "results.tsv"
        baseline = run(
            py("skill_autoresearch_eval.py")
            + [
                "--repo",
                str(repo),
                "--pack",
                str(pack),
                "--diff-ref",
                "HEAD",
                "--format",
                "json",
                "--results-tsv",
                str(results_tsv),
                "--description",
                "baseline",
            ]
        )
        payload = json.loads(baseline.stdout)
        if payload.get("status") != "pass":
            raise RuntimeError(f"Expected baseline pass, got:\n{baseline.stdout}\n{baseline.stderr}")
        if payload.get("score") != 100:
            raise RuntimeError(f"Expected score 100, got {payload.get('score')}")
        if payload.get("scope_ok") is not True or payload.get("worktree_clean") is not True:
            raise RuntimeError(f"Expected clean scope/worktree, got:\n{baseline.stdout}")
        results_lines = results_tsv.read_text(encoding="utf-8").splitlines()
        if len(results_lines) != 2 or not results_lines[0].startswith("commit\tscore\tpassed"):
            raise RuntimeError(f"Unexpected TSV contents:\n{results_tsv.read_text(encoding='utf-8')}")

        (repo / "blocked.txt").write_text("changed\n", encoding="utf-8")
        git(repo, "add", "blocked.txt")
        git(repo, "commit", "-m", "unauthorized")

        unauthorized = run(
            py("skill_autoresearch_eval.py")
            + [
                "--repo",
                str(repo),
                "--pack",
                str(pack),
                "--diff-ref",
                "HEAD~1",
                "--format",
                "json",
            ],
            check=False,
        )
        if unauthorized.returncode == 0:
            raise RuntimeError(f"Expected unauthorized scope failure, got:\n{unauthorized.stdout}\n{unauthorized.stderr}")
        rejected = json.loads(unauthorized.stdout)
        if rejected.get("failure_reasons") != ["scope_violation"]:
            raise RuntimeError(f"Expected scope_violation, got:\n{unauthorized.stdout}")
        scope = rejected.get("scope") if isinstance(rejected.get("scope"), dict) else {}
        if scope.get("unauthorized_files") != ["blocked.txt"]:
            raise RuntimeError(f"Expected blocked.txt unauthorized, got:\n{unauthorized.stdout}")
        if rejected.get("benchmarks") != []:
            raise RuntimeError(f"Expected benchmarks to be skipped on scope rejection, got:\n{unauthorized.stdout}")

    print("SKILL AUTORESEARCH EVAL TEST PASSED")


if __name__ == "__main__":
    main()
