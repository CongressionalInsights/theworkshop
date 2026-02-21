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


def run(cmd: list[str], *, env: dict[str, str] | None = None, check: bool = True, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    merged = dict(os.environ)
    merged["THEWORKSHOP_NO_OPEN"] = "1"
    merged["THEWORKSHOP_NO_MONITOR"] = "1"
    merged["THEWORKSHOP_NO_KEYCHAIN"] = "1"
    if env:
        merged.update(env)

    proc = subprocess.run(cmd, text=True, capture_output=True, env=merged, cwd=str(cwd) if cwd else None)
    if check and proc.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            f"  cmd={' '.join(cmd)}\n"
            f"  exit={proc.returncode}\n"
            f"  stdout:\n{proc.stdout}\n"
            f"  stderr:\n{proc.stderr}"
        )
    return proc


def py(script: str) -> list[str]:
    return [sys.executable, str(SCRIPTS_DIR / script)]


def set_frontmatter(path: Path, **updates) -> None:
    doc = split_frontmatter(path.read_text(encoding="utf-8", errors="ignore"))
    for key, value in updates.items():
        doc.frontmatter[key] = value
    path.write_text(join_frontmatter(doc), encoding="utf-8")


def get_frontmatter(path: Path) -> dict:
    return split_frontmatter(path.read_text(encoding="utf-8", errors="ignore")).frontmatter


def find_job_dir(project_root: Path, wi: str) -> Path:
    matches = list(project_root.glob(f"workstreams/WS-*/jobs/{wi}-*"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly 1 job dir for {wi}, got {len(matches)}: {matches}")
    return matches[0]


def make_fake_codex_script(shim_dir: Path) -> None:
    script = shim_dir / "codex"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "from __future__ import annotations\n"
        "\n"
        "import os\n"
        "import sys\n"
        "import time\n"
        "from pathlib import Path\n"
        "\n"
        "\n"
        "def main() -> int:\n"
        "    args = sys.argv[1:]\n"
        "    if not args or args[0] != \"exec\":\n"
        "        print(\"fake codex shim expects `exec`\", file=sys.stderr)\n"
        "        return 2\n"
        "\n"
        "    output_file = None\n"
        "    try:\n"
        "        idx = args.index(\"--output-last-message\")\n"
        "        output_file = args[idx + 1]\n"
        "    except Exception:\n"
        "        output_file = None\n"
        "\n"
        "    promise = os.environ.get(\"LOOP_SHIM_PROMISE\", \"\")\n"
        "    sleep_ms = os.environ.get(\"LOOP_SHIM_SLEEP_MS\", \"0\")\n"
        "    try:\n"
        "        sleep_sec = float(sleep_ms) / 1000.0\n"
        "        if sleep_sec > 0:\n"
        "            time.sleep(sleep_sec)\n"
        "    except Exception:\n"
        "        pass\n"
        "\n"
        "    if output_file:\n"
        "        Path(output_file).write_text(promise, encoding=\"utf-8\")\n"
        "\n"
        "    try:\n"
        "        code = int(os.environ.get(\"LOOP_SHIM_EXIT_CODE\", \"0\"))\n"
        "    except Exception:\n"
        "        code = 1\n"
        "    return code\n"
        "\n"
        "\n"
        "if __name__ == \"__main__\":\n"
        "    raise SystemExit(main())\n",
        encoding="utf-8",
    )
    script.chmod(0o755)


def bootstrap_project(base_dir: Path) -> tuple[Path, str]:
    proj = run(py("project_new.py") + ["--name", "TheWorkshop Loop Test", "--base-dir", str(base_dir)]).stdout.strip()
    project_root = Path(proj).resolve()

    ws_id = run(py("workstream_add.py") + ["--project", str(project_root), "--title", "Execution"]).stdout.strip()
    wi = run(
        py("job_add.py")
        + [
            "--project",
            str(project_root),
            "--workstream",
            ws_id,
            "--title",
            "Loop Job",
            "--stakes",
            "normal",
        ]
    ).stdout.strip()

    set_frontmatter(
        project_root / "plan.md",
        agreement_status="agreed",
        agreed_at=now_iso(),
        agreed_notes="loop test agreement",
        status="in_progress",
        updated_at=now_iso(),
    )

    job_dir = find_job_dir(project_root, wi)
    set_frontmatter(
        project_root / "plan.md",
        max_iterations=3,
    )
    set_frontmatter(
        job_dir / "plan.md",
        reward_target=0,
        loop_enabled=False,
        loop_mode="",
        loop_max_iterations=0,
        loop_target_promise="",
        loop_status="",
        loop_last_attempt=0,
        loop_last_started_at="",
        loop_last_stopped_at="",
        loop_stop_reason="",
    )
    prompt_path = job_dir / "prompt.md"
    prompt_path.write_text(
        f"Work on WI {wi}. When finished and verified, output <promise>{wi}-DONE</promise>\n",
        encoding="utf-8",
    )
    write_job_artifacts(job_dir, wi=wi)
    return project_root, wi


def write_job_artifacts(job_dir: Path, wi: str) -> None:
    outputs = job_dir / "outputs"
    artifacts = job_dir / "artifacts"
    outputs.mkdir(exist_ok=True)
    artifacts.mkdir(exist_ok=True)
    (outputs / "primary.md").write_text(
        "\n".join(
            [
                f"# Output for {wi}",
                "",
                "Paragraph 1: test output.",
                "",
                "Paragraph 2: test output.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (artifacts / "verification.md").write_text(
        f"Verified for {wi} at {now_iso()}\n",
        encoding="utf-8",
    )


def run_loop(
    project_root: Path,
    fake_codex_dir: Path,
    wi: str,
    mode: str,
    max_loops: int,
    *,
    completion_promise: str = "",
    promise: str = "",
    exit_code: str = "0",
    walltime_sec: int | None = None,
    sleep_ms: str = "0",
) -> subprocess.CompletedProcess[str]:
    env = {
        "LOOP_SHIM_PROMISE": promise,
        "LOOP_SHIM_EXIT_CODE": str(exit_code),
        "LOOP_SHIM_SLEEP_MS": str(sleep_ms),
        "PATH": fake_codex_dir.as_posix() + os.pathsep + os.environ.get("PATH", ""),
    }

    args = [
        sys.executable,
        str(SCRIPTS_DIR / "loop_job.py"),
        "--project",
        str(project_root),
        "--work-item-id",
        wi,
        "--mode",
        mode,
        "--max-loops",
        str(int(max_loops)),
        "--no-preflight",
        "--no-open",
        "--no-dashboard",
    ]
    if completion_promise:
        args += ["--completion-promise", completion_promise]
    if walltime_sec is not None and walltime_sec > 0:
        args += ["--max-walltime-sec", str(int(walltime_sec))]

    return run(args, env=env, check=False)


def assert_loop_state(project_root: Path, wi: str, *, expected: dict[str, object]) -> dict[str, object]:
    fm = get_frontmatter(find_job_dir(project_root, wi) / "plan.md")
    for key, value in expected.items():
        if str(fm.get(key)) != str(value):
            raise RuntimeError(
                f"Expected {wi} frontmatter[{key!r}]={value!r}, got {fm.get(key)!r}\n"
                f"frontmatter: {fm}"
            )
    return fm


def make_cancel_marker(project_root: Path, wi: str) -> None:
    cancel_file = project_root / ".theworkshop" / "loops" / wi / "cancel"
    cancel_file.parent.mkdir(parents=True, exist_ok=True)
    cancel_file.write_text("cancel test", encoding="utf-8")


def scenario_success_with_promise(tmp_root: Path, fake_codex_dir: Path) -> None:
    project_root, wi = bootstrap_project(tmp_root)
    code = run_loop(
        project_root=project_root,
        fake_codex_dir=fake_codex_dir,
        wi=wi,
        mode="until_complete",
        max_loops=2,
        completion_promise=f"{wi}-DONE",
        promise=f"<promise>{wi}-DONE</promise>",
    )
    if code.returncode != 0:
        raise RuntimeError(f"Loop job should succeed, got {code.returncode}: {code.stdout}\n{code.stderr}")

    fm = assert_loop_state(
        project_root,
        wi,
        expected={
            "status": "done",
            "loop_enabled": True,
            "loop_status": "completed",
            "loop_last_attempt": 1,
            "loop_stop_reason": "promise_detected",
        },
    )
    if str(fm.get("loop_last_stopped_at", "")) == "":
        raise RuntimeError(f"Expected loop_last_stopped_at to be set: {fm}")


def scenario_max_iterations_blocked(tmp_root: Path, fake_codex_dir: Path) -> None:
    project_root, wi = bootstrap_project(tmp_root)
    code = run_loop(
        project_root=project_root,
        fake_codex_dir=fake_codex_dir,
        wi=wi,
        mode="until_complete",
        max_loops=2,
        completion_promise=f"{wi}-DONE",
        promise="",
    )
    if code.returncode != 1:
        raise RuntimeError(f"Expected blocked loop to exit 1, got {code.returncode}: {code.stdout}\n{code.stderr}")

    assert_loop_state(
        project_root,
        wi,
        expected={
            "loop_status": "blocked",
            "loop_last_attempt": 2,
            "loop_stop_reason": "max_iterations",
        },
    )


def scenario_exec_exit_error(tmp_root: Path, fake_codex_dir: Path) -> None:
    project_root, wi = bootstrap_project(tmp_root)
    code = run_loop(
        project_root=project_root,
        fake_codex_dir=fake_codex_dir,
        wi=wi,
        mode="until_complete",
        max_loops=2,
        completion_promise=f"{wi}-DONE",
        promise=f"<promise>{wi}-DONE</promise>",
        exit_code="7",
    )
    if code.returncode != 7:
        raise RuntimeError(f"Expected codex exit code to surface, got {code.returncode}: {code.stdout}\n{code.stderr}")

    fm = assert_loop_state(
        project_root,
        wi,
        expected={
            "loop_status": "error",
            "loop_last_attempt": 1,
            "loop_stop_reason": "exit_code_7",
        },
    )
    if str(fm.get("status")) != "in_progress":
        raise RuntimeError(f"Expected job to remain in_progress on loop error, got status={fm.get('status')!r}")


def scenario_cancel_before_start(tmp_root: Path, fake_codex_dir: Path) -> None:
    project_root, wi = bootstrap_project(tmp_root)
    make_cancel_marker(project_root, wi)
    code = run_loop(
        project_root=project_root,
        fake_codex_dir=fake_codex_dir,
        wi=wi,
        mode="max_iterations",
        max_loops=3,
    )
    if code.returncode != 1:
        raise RuntimeError(f"Expected cancel signal to exit 1, got {code.returncode}")

    assert_loop_state(
        project_root,
        wi,
        expected={
            "loop_status": "stopped",
            "loop_last_attempt": 1,
            "loop_stop_reason": "cancel",
        },
    )


def scenario_timeout(tmp_root: Path, fake_codex_dir: Path) -> None:
    project_root, wi = bootstrap_project(tmp_root)
    code = run_loop(
        project_root=project_root,
        fake_codex_dir=fake_codex_dir,
        wi=wi,
        mode="until_complete",
        max_loops=5,
        completion_promise=f"{wi}-DONE",
        promise="",
        walltime_sec=1,
        sleep_ms="1250",
    )
    if code.returncode != 1:
        raise RuntimeError(f"Expected timeout stop to return 1, got {code.returncode}")

    fm = assert_loop_state(
        project_root,
        wi,
        expected={
            "loop_status": "blocked",
            "loop_last_attempt": 1,
            "loop_stop_reason": "timeout",
        },
    )
    if str(fm.get("loop_last_stopped_at", "")) == "":
        raise RuntimeError(f"Expected loop_last_stopped_at to be set for timeout: {fm}")


def scenario_malformed_promise(tmp_root: Path, fake_codex_dir: Path) -> None:
    project_root, wi = bootstrap_project(tmp_root)
    code = run_loop(
        project_root=project_root,
        fake_codex_dir=fake_codex_dir,
        wi=wi,
        mode="until_complete",
        max_loops=2,
        completion_promise="<bad-promise>",
    )
    if code.returncode == 0:
        raise RuntimeError("Expected malformed completion promise to fail fast")
    if code.returncode > 1:
        # Non-zero is expected; validate error text for clarity.
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Integration-style tests for theworkshop loop execution.")
    parser.add_argument("--keep", action="store_true", help="Keep temp directory for inspection.")
    parser.add_argument("--temp", action="store_true", help="Force temp execution (default is repo/_test_runs).")
    args = parser.parse_args()

    base_root = Path(tempfile.mkdtemp(prefix="theworkshop-loop-job-test-")) if args.temp else SCRIPTS_DIR.parent / "_test_runs" / "loop-job-tests"
    base_root.mkdir(parents=True, exist_ok=True)
    fake_codex_dir = base_root / "tmp"
    fake_codex_dir.mkdir(parents=True, exist_ok=True)
    make_fake_codex_script(fake_codex_dir)

    project_base = base_root / "projects"
    project_base.mkdir(exist_ok=True)

    tmp = tempfile.TemporaryDirectory(prefix="loop-job-scenarios-", dir=str(project_base))
    root = Path(tmp.name).resolve()

    try:
        scenario_success_with_promise(root, fake_codex_dir)
        scenario_max_iterations_blocked(root, fake_codex_dir)
        scenario_exec_exit_error(root, fake_codex_dir)
        scenario_cancel_before_start(root, fake_codex_dir)
        scenario_timeout(root, fake_codex_dir)
        scenario_malformed_promise(root, fake_codex_dir)
    finally:
        if args.keep:
            print(f"KEPT: {root}")
            print(root)
        else:
            tmp.cleanup()
            print("LOOP JOB TEST PASSED")


if __name__ == "__main__":
    main()
