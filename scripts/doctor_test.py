#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Allow importing TheWorkshop helpers from the scripts directory.
SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))


def run(cmd: list[str], *, env: dict[str, str] | None = None, check: bool = True, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    merged = dict(os.environ)
    merged["THEWORKSHOP_NO_OPEN"] = "1"
    merged["THEWORKSHOP_NO_MONITOR"] = "1"
    if env:
        merged.update(env)
    proc = subprocess.run(cmd, text=True, capture_output=True, env=merged, cwd=str(cwd) if cwd else None)
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


def write_fake_session_log(root: Path, session_id: str) -> None:
    sessions_dir = root / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    log = sessions_dir / f"rollout-{session_id}-test.jsonl"
    payload = {
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": {"total_tokens": 42},
            },
        },
    }
    log.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="theworkshop-doctor-test-") as tmp_dir:
        code_home = Path(tmp_dir).resolve()

        # imagegen skill path must exist for DOCTOR preflight checks.
        (code_home / "skills" / "imagegen" / "scripts").mkdir(parents=True, exist_ok=True)
        (code_home / "skills" / "imagegen" / "scripts" / "image_gen.py").write_text(
            "#! /usr/bin/env python3\nprint('ok')\n",
            encoding="utf-8",
        )

        session_id = "WI-DOCTOR-TEST-001"
        write_fake_session_log(code_home, session_id)

        env_ok = {
            "CODEX_HOME": str(code_home),
            "THEWORKSHOP_IMAGEGEN_API_KEY": "unit-test-key",
            "CODEX_THREAD_ID": session_id,
        }
        proc_ok = run(py("doctor.py"), env=env_ok)
        if proc_ok.returncode != 0:
            raise RuntimeError(
                "doctor.py should pass with canonical env image credential + session log\n"
                f"stdout:\n{proc_ok.stdout}\n"
                f"stderr:\n{proc_ok.stderr}"
            )
        if "DOCTOR: OK" not in proc_ok.stdout:
            raise RuntimeError(f"Expected DOCTOR: OK, got:\n{proc_ok.stdout}")
        if "image credentials:" not in proc_ok.stdout or "env:THEWORKSHOP_IMAGEGEN_API_KEY" not in proc_ok.stdout:
            raise RuntimeError(f"Expected env credential status, got:\n{proc_ok.stdout}")

        env_missing = {
            "CODEX_HOME": str(code_home),
            "THEWORKSHOP_IMAGEGEN_API_KEY": "",
            "THEWORKSHOP_NO_KEYCHAIN": "1",
            "CODEX_THREAD_ID": session_id,
        }
        proc_fail = run(py("doctor.py"), env=env_missing, check=False)
        if proc_fail.returncode == 0:
            raise RuntimeError(
                "doctor.py should fail when no env credential is available and keychain is disabled\n"
                f"stdout:\n{proc_fail.stdout}\n"
                f"stderr:\n{proc_fail.stderr}"
            )
        if "Set THEWORKSHOP_IMAGEGEN_API_KEY" not in (proc_fail.stdout + proc_fail.stderr):
            raise RuntimeError(f"Expected credential guidance, got:\n{proc_fail.stdout}\n{proc_fail.stderr}")
        if "DOCTOR: FAIL" not in (proc_fail.stdout + proc_fail.stderr):
            raise RuntimeError(f"Expected DOCTOR: FAIL, got:\n{proc_fail.stdout}\n{proc_fail.stderr}")

        print("DOCTOR TESTS PASSED")


if __name__ == "__main__":
    main()
