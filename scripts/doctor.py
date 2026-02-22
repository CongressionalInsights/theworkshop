#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

from twlib import codex_home, codex_session_token_snapshot

from imagegen_job import (
    CANONICAL_IMAGEGEN_PROVIDER_DEFAULT,
    THEWORKSHOP_IMAGEGEN_CREDENTIAL_SOURCE,
    THEWORKSHOP_IMAGEGEN_API_KEY,
    THEWORKSHOP_NO_KEYCHAIN,
    resolve_imagegen_credential_provider,
    resolve_keychain_runner,
)


def _env_value(key: str) -> str:
    return str(os.environ.get(key, "")).strip()


def session_id() -> str:
    for k in ("THEWORKSHOP_SESSION_ID", "CODEX_THREAD_ID", "TERM_SESSION_ID", "ITERM_SESSION_ID"):
        v = _env_value(k)
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


def image_credential_ok() -> tuple[bool, str]:
    no_keychain = _env_value(THEWORKSHOP_NO_KEYCHAIN) == "1"
    requested_provider = _env_value(THEWORKSHOP_IMAGEGEN_CREDENTIAL_SOURCE) or CANONICAL_IMAGEGEN_PROVIDER_DEFAULT
    try:
        resolution = resolve_imagegen_credential_provider(
            requested_provider,
            approve="ttl:1h",
            no_keychain=no_keychain,
        )
        return True, resolution.source
    except SystemExit as exc:
        return False, str(exc)


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

    cred_ok, cred_detail = image_credential_ok()
    if cred_ok:
        print(f"[OK] image credentials: {cred_detail}")
    else:
        print(f"[FAIL] image credentials: {cred_detail}")
        failures.append(
            f"Set {THEWORKSHOP_IMAGEGEN_API_KEY} (recommended) for non-Apple environments. "
            f"Optionally install apple-keychain and set service credentials for `keychain` mode."
        )

    # Show keychain path status only when meaningful.
    if cred_ok and cred_detail.startswith("keychain:"):
        selected_provider = _env_value(THEWORKSHOP_IMAGEGEN_CREDENTIAL_SOURCE).lower() or "auto"
        keychain_runner = resolve_keychain_runner(os.environ)
        keychain_runner_ok = keychain_runner.exists()
        print(
            f"[{'OK' if keychain_runner_ok else 'FAIL'}] apple-keychain skill: {keychain_runner}"
        )
        if not keychain_runner_ok and selected_provider == "keychain":
            failures.append(
                "Install the `apple-keychain` skill under $CODEX_HOME/skills/apple-keychain "
                "or switch image credentials to env mode."
            )
    elif cred_ok:
        print("[OK] apple-keychain skill: not selected")

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
        print(f"- note: {n}")


if __name__ == "__main__":
    main()
