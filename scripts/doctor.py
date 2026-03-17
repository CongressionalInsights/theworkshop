#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os

from runtime_profile import (
    command_available,
    resolve_doctor_profile,
    session_logs_exist,
    skill_script_path,
)
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


def selected_imagegen_provider() -> str:
    requested = _env_value(THEWORKSHOP_IMAGEGEN_CREDENTIAL_SOURCE).lower() or CANONICAL_IMAGEGEN_PROVIDER_DEFAULT
    if requested in {"env", "keychain"}:
        return requested
    return ""


def image_credential_status(*, strict: bool) -> tuple[bool, str]:
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
        detail = str(exc)
        if strict:
            return False, detail
        return True, detail


def print_status(level: str, label: str, detail: str) -> None:
    print(f"[{level}] {label}: {detail}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Preflight checks for TheWorkshop public OSS baseline and Codex profile.")
    parser.add_argument("--profile", choices=["codex", "portable"], default="codex")
    args = parser.parse_args()

    profile = resolve_doctor_profile(args.profile)
    failures: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []
    ch = codex_home()

    print_status("OK", "profile", profile)
    notes.append(
        "public OSS baseline only; private/custom operator behavior remains outside the repo contract"
    )

    imagegen_mode = selected_imagegen_provider()
    imagegen_strict = bool(imagegen_mode)

    uv_ok = command_available("uv")
    uv_level = "OK" if uv_ok else "FAIL" if imagegen_strict else "WARN"
    print_status(uv_level, "uv", "available" if uv_ok else "missing")
    if not uv_ok:
        msg = "Install `uv` for the optional imagegen/OpenAI adapter path."
        (failures if imagegen_strict else warnings).append(msg)

    imagegen_cli = skill_script_path("imagegen", "scripts/image_gen.py")
    imagegen_ok = imagegen_cli.exists()
    imagegen_level = "OK" if imagegen_ok else "FAIL" if imagegen_strict else "WARN"
    print_status(imagegen_level, "imagegen adapter", str(imagegen_cli))
    if not imagegen_ok:
        msg = "Optional adapter missing: install the `imagegen` skill under $CODEX_HOME/skills/imagegen."
        (failures if imagegen_strict else warnings).append(msg)

    cred_ok, cred_detail = image_credential_status(strict=imagegen_strict)
    cred_configured = cred_detail.startswith(("env:", "keychain:"))
    cred_level = "OK" if cred_ok and cred_configured else "WARN" if cred_ok else "FAIL"
    print_status(cred_level, "image credentials", cred_detail)
    if not cred_ok:
        failures.append(
            f"Set {THEWORKSHOP_IMAGEGEN_API_KEY} (recommended) or switch the selected imagegen adapter mode."
        )
    elif not imagegen_strict and not cred_configured:
        warnings.append(f"imagegen adapter not configured: {cred_detail}")

    selected_provider = _env_value(THEWORKSHOP_IMAGEGEN_CREDENTIAL_SOURCE).lower() or "auto"
    keychain_runner = resolve_keychain_runner(os.environ)
    keychain_runner_ok = keychain_runner.exists()
    keychain_required = selected_provider == "keychain"
    keychain_level = "OK" if keychain_runner_ok else "FAIL" if keychain_required else "WARN"
    detail = str(keychain_runner) if keychain_required or keychain_runner_ok else "not selected"
    print_status(keychain_level, "apple-keychain adapter", detail)
    if not keychain_runner_ok and keychain_required:
        failures.append(
            "Selected adapter requires `apple-keychain`; install it under $CODEX_HOME/skills/apple-keychain."
        )
    elif not keychain_runner_ok:
        warnings.append("apple-keychain adapter not installed (optional).")

    gemini_ok = command_available("gemini")
    print_status("OK" if gemini_ok else "WARN", "gemini adapter", "available" if gemini_ok else "missing")
    if not gemini_ok:
        warnings.append("Gemini planner adapter not installed or not on PATH (optional).")

    gh_ok = command_available("gh")
    print_status("OK" if gh_ok else "WARN", "github adapter", "available" if gh_ok else "missing")
    if not gh_ok:
        warnings.append("GitHub adapter (`gh`) not installed (optional).")

    codexbar_ok = command_available("codexbar")
    print_status("OK" if codexbar_ok else "WARN", "codexbar adapter", "available" if codexbar_ok else "missing")
    if not codexbar_ok:
        warnings.append("Exact CodexBar billing adapter not installed; spend falls back to session-log heuristics when available.")

    sid = session_id()
    logs_ok = session_logs_exist(sid, ch)
    snap = codex_session_token_snapshot("codex")
    snap_ok = bool(snap)
    telemetry_required = profile == "codex"
    logs_level = "OK" if logs_ok else "FAIL" if telemetry_required else "WARN"
    snap_level = "OK" if snap_ok else "FAIL" if telemetry_required else "WARN"
    print_status(logs_level, "codex session logs", sid or "(missing)")
    print_status(snap_level, "codex token snapshot", "parseable" if snap_ok else "unavailable")
    if telemetry_required:
        if not sid:
            failures.append("Codex profile requires CODEX_THREAD_ID/SESSION_ID from a Codex Desktop session.")
        elif not logs_ok:
            failures.append("Codex profile requires matching rollout JSONL under $CODEX_HOME/sessions.")
        elif not snap_ok:
            failures.append("Codex profile found session logs but no parseable token_count telemetry.")
    else:
        if not sid or not logs_ok or not snap_ok:
            warnings.append("Codex telemetry adapter unavailable; portable profile treats this as optional.")
    if snap and snap.get("sessionLogPath"):
        notes.append(f"token snapshot source: {snap.get('source')} ({snap.get('sessionLogPath')})")

    print("")
    if failures:
        print("DOCTOR: FAIL")
        for f in failures:
            print(f"- {f}")
        for w in warnings:
            print(f"- warning: {w}")
        for n in notes:
            print(f"- note: {n}")
        raise SystemExit(1)

    print("DOCTOR: OK")
    for w in warnings:
        print(f"- warning: {w}")
    for n in notes:
        print(f"- note: {n}")


if __name__ == "__main__":
    main()
