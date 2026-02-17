#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

from twlib import codex_home, codex_session_token_snapshot


def check_keychain_service(service: str) -> bool:
    proc = subprocess.run(
        ["security", "find-generic-password", "-s", service],
        text=True,
        capture_output=True,
    )
    return int(proc.returncode) == 0


def session_id() -> str:
    for k in ("THEWORKSHOP_SESSION_ID", "CODEX_THREAD_ID", "TERM_SESSION_ID", "ITERM_SESSION_ID"):
        v = str(os.environ.get(k) or "").strip()
        if v:
            return v
    return ""


def session_logs_exist(sid: str, root: Path) -> bool:
    if not sid:
        return False
    sessions = root / "sessions"
    if not sessions.exists():
        return False
    try:
        return any(sid in p.name for p in sessions.rglob("rollout-*.jsonl"))
    except Exception:
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Preflight checks for TheWorkshop one-pass reliability.")
    parser.parse_args()

    failures: list[str] = []
    notes: list[str] = []
    ch = codex_home()

    uv_ok = bool(shutil.which("uv"))
    print(f"[{'OK' if uv_ok else 'FAIL'}] uv available")
    if not uv_ok:
        failures.append("Install `uv` so imagegen jobs can run with managed dependencies.")

    imagegen_cli = ch / "skills" / "imagegen" / "scripts" / "image_gen.py"
    imagegen_ok = imagegen_cli.exists()
    print(f"[{'OK' if imagegen_ok else 'FAIL'}] imagegen skill: {imagegen_cli}")
    if not imagegen_ok:
        failures.append("Install the `imagegen` skill under $CODEX_HOME/skills/imagegen.")

    keychain_runner = ch / "skills" / "apple-keychain" / "scripts" / "keychain_run.sh"
    keychain_ok = keychain_runner.exists()
    print(f"[{'OK' if keychain_ok else 'FAIL'}] apple-keychain skill: {keychain_runner}")
    if not keychain_ok:
        failures.append("Install the `apple-keychain` skill under $CODEX_HOME/skills/apple-keychain.")

    key_openai = check_keychain_service("OPENAI_KEY")
    key_legacy = check_keychain_service("OPENAI_API_KEY")
    key_ok = key_openai or key_legacy
    service_label = "OPENAI_KEY" if key_openai else "OPENAI_API_KEY" if key_legacy else "missing"
    print(f"[{'OK' if key_ok else 'FAIL'}] keychain item: {service_label}")
    if not key_ok:
        failures.append("Add a generic password in macOS Keychain with service `OPENAI_KEY`.")

    sid = session_id()
    logs_ok = session_logs_exist(sid, ch)
    snap = codex_session_token_snapshot("codex")
    snap_ok = bool(snap)
    print(f"[{'OK' if logs_ok else 'FAIL'}] session logs for current thread id: {sid or '(missing)'}")
    print(f"[{'OK' if snap_ok else 'FAIL'}] token snapshot parseable from session logs")
    if not sid:
        failures.append("Current shell does not expose CODEX_THREAD_ID/SESSION_ID; launch inside Codex Desktop session.")
    elif not logs_ok:
        failures.append("No matching rollout JSONL found under $CODEX_HOME/sessions for current thread id.")
    elif not snap_ok:
        failures.append("Session log found but no token_count entries were parseable.")
    if snap and snap.get("sessionLogPath"):
        notes.append(f"token snapshot source: {snap.get('source')} ({snap.get('sessionLogPath')})")

    print("")
    if failures:
        print("DOCTOR: FAIL")
        for f in failures:
            print(f"- {f}")
        for n in notes:
            print(f"- note: {n}")
        raise SystemExit(1)

    print("DOCTOR: OK")
    for n in notes:
        print(f"- {n}")


if __name__ == "__main__":
    main()
