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
from twyaml import MarkdownDoc, join_frontmatter, parse_yaml_lite, split_frontmatter  # noqa: E402


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


def assert_true(cond: bool, msg: str) -> None:
    if not cond:
        raise RuntimeError(msg)


def expect_fail(cmd: list[str], *, contains: str | None = None, cwd: Path | None = None) -> None:
    proc = run(cmd, cwd=cwd, check=False)
    if proc.returncode == 0:
        raise RuntimeError(f"Expected command to fail but it succeeded: {' '.join(cmd)}")
    if contains:
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        if contains not in out:
            raise RuntimeError(
                "Expected failure output to contain substring:\n"
                f"  substring={contains!r}\n"
                f"  stdout:\n{proc.stdout}\n"
                f"  stderr:\n{proc.stderr}\n"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="TheWorkshop edge-case tests (temp project + control-plane gates).")
    parser.add_argument("--keep", action="store_true", help="Keep the temp project directory")
    args = parser.parse_args()

    # YAML-lite: float parsing + empty containers.
    fm = parse_yaml_lite("estimate_hours: 1.25\nok: true\nempty_list: []\nempty_dict: {}\n")
    assert_true(isinstance(fm.get("estimate_hours"), float), "YAML-lite did not parse float estimate_hours")
    assert_true(abs(float(fm["estimate_hours"]) - 1.25) < 1e-9, "YAML-lite float value mismatch")
    assert_true(fm.get("ok") is True, "YAML-lite did not parse bool true")
    assert_true(fm.get("empty_list") == [], "YAML-lite did not parse [] as empty list")
    assert_true(fm.get("empty_dict") == {}, "YAML-lite did not parse {} as empty dict")

    # YAML-lite: unknown keys roundtrip (parse -> join -> parse).
    doc0 = MarkdownDoc(
        frontmatter={
            "schema": "theworkshop.plan.v1",
            "kind": "project",
            "id": "PJ-TEST",
            "title": "Roundtrip",
            "status": "planned",
            "agreement_status": "proposed",
            "started_at": now_iso(),
            "updated_at": now_iso(),
            "completion_promise": "PJ-TEST-DONE",
            "unknown_scalar": "keep-me",
            "unknown_list": ["a", "b"],
            "unknown_dict": {"x": 1, "y": "z"},
            "unknown_list_of_dicts": [
                {"id": "WV-TEST-001", "title": "Wave 1"},
                {"id": "WV-TEST-002", "title": "Wave 2"},
            ],
        },
        body="# Goal\n\nTest\n",
    )
    doc1 = split_frontmatter(join_frontmatter(doc0))
    assert_true(doc1.frontmatter.get("unknown_scalar") == "keep-me", "Unknown scalar key was not preserved")
    assert_true(doc1.frontmatter.get("unknown_list") == ["a", "b"], "Unknown list key was not preserved")
    assert_true(doc1.frontmatter.get("unknown_dict") == {"x": 1, "y": "z"}, "Unknown dict key was not preserved")
    assert_true(
        doc1.frontmatter.get("unknown_list_of_dicts")
        == [
            {"id": "WV-TEST-001", "title": "Wave 1"},
            {"id": "WV-TEST-002", "title": "Wave 2"},
        ],
        "Unknown list-of-dicts key was not preserved",
    )

    tmp = tempfile.TemporaryDirectory(prefix="theworkshop-edge-")
    base_dir = Path(tmp.name).resolve()
    base_dir.mkdir(parents=True, exist_ok=True)
    print(f"[1] Base dir: {base_dir}")

    # Create project
    proj = run(py("project_new.py") + ["--name", "TheWorkshop Edge Test", "--base-dir", str(base_dir)]).stdout.strip()
    project_root = Path(proj).resolve()
    print(f"[2] Project: {project_root}")

    # Inject an unknown frontmatter key into the project plan, then mutate via workstream_add.
    proj_plan = project_root / "plan.md"
    set_frontmatter(proj_plan, unknown_project_key="keep-me")

    ws_id = run(py("workstream_add.py") + ["--project", str(project_root), "--title", "Stream A"]).stdout.strip()
    print(f"[3] Workstream: {ws_id}")

    proj_doc = split_frontmatter(proj_plan.read_text(encoding="utf-8", errors="ignore"))
    assert_true(proj_doc.frontmatter.get("unknown_project_key") == "keep-me", "Unknown project key was not preserved")

    wi_id = run(
        py("job_add.py") + ["--project", str(project_root), "--workstream", ws_id, "--title", "Job A", "--stakes", "low"]
    ).stdout.strip()
    print(f"[4] Job: {wi_id}")

    # Agreement gate: any execution state requires agreement_status=agreed.
    job_plan = next(project_root.glob("workstreams/WS-*/jobs/WI-*/plan.md"))
    set_frontmatter(job_plan, status="in_progress", started_at=now_iso(), updated_at=now_iso())
    expect_fail(py("plan_check.py") + ["--project", str(project_root)], contains="agreement_status must be 'agreed'")
    print("[5] agreement gate: OK (failed as expected)")

    # Flip agreement, then plan_check should pass.
    set_frontmatter(
        proj_plan,
        agreement_status="agreed",
        agreed_at=now_iso(),
        agreed_notes="edge test auto-agree",
        status="in_progress",
        updated_at=now_iso(),
    )
    run(py("plan_sync.py") + ["--project", str(project_root)])
    run(py("plan_check.py") + ["--project", str(project_root)])
    print("[6] agreement satisfied: OK")

    # Heading gate: remove required heading, ensure plan_check fails.
    jd = split_frontmatter(job_plan.read_text(encoding="utf-8", errors="ignore"))
    orig_body = jd.body
    jd.body = orig_body.replace("# Verification\n", "", 1)
    job_plan.write_text(join_frontmatter(jd), encoding="utf-8")
    expect_fail(py("plan_check.py") + ["--project", str(project_root)], contains="# Verification")
    print("[7] missing heading gate: OK (failed as expected)")

    # Restore body and pass.
    jd.body = orig_body
    job_plan.write_text(join_frontmatter(jd), encoding="utf-8")
    run(py("plan_check.py") + ["--project", str(project_root)])
    print("[8] heading restored: OK")

    # Iteration budget gate: iteration>max_iterations must be blocked (or reward_eval will auto-block).
    jd = split_frontmatter(job_plan.read_text(encoding="utf-8", errors="ignore"))
    max_iter = int(jd.frontmatter.get("max_iterations") or 0) or 1
    set_frontmatter(job_plan, iteration=max_iter + 1, status="in_progress", updated_at=now_iso())
    expect_fail(py("plan_check.py") + ["--project", str(project_root)], contains="exceeds max_iterations")
    print("[9] iteration budget gate: OK (failed as expected)")

    # reward_eval should auto-block the job, then plan_check should pass.
    run(py("reward_eval.py") + ["--project", str(project_root), "--work-item-id", wi_id])
    run(py("plan_check.py") + ["--project", str(project_root)])
    print("[10] reward_eval auto-block: OK")

    print("")
    print("EDGE TEST PASSED")
    print(f"Project root: {project_root}")

    if not args.keep:
        tmp.cleanup()


if __name__ == "__main__":
    main()
