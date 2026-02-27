#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from imagegen_job import build_imagegen_run_env, should_retry_keychain_headless  # noqa: E402


def main() -> None:
    if should_retry_keychain_headless("", "HTTP 429 too many requests"):
        raise RuntimeError("Expected no keychain retry for plain API rate-limit error")

    timed_out = should_retry_keychain_headless(
        "security keychain run",
        "Timed out waiting for keychain approval dialog",
    )
    if not timed_out:
        raise RuntimeError("Expected keychain retry for approval timeout failures")

    env = build_imagegen_run_env(
        provider="keychain",
        source="keychain:OPENAI_KEY",
        overrides={},
        base_env={},
        no_keychain=False,
    )
    if str(env.get("CODEX_KEYCHAIN_DIALOG_TIMEOUT") or "") != "30s":
        raise RuntimeError(f"Expected CODEX_KEYCHAIN_DIALOG_TIMEOUT=30s, got {env.get('CODEX_KEYCHAIN_DIALOG_TIMEOUT')!r}")
    if not sys.stdin.isatty() and str(env.get("CODEX_KEYCHAIN_APPROVE") or "") != "1":
        raise RuntimeError("Expected CODEX_KEYCHAIN_APPROVE=1 in non-interactive mode")

    print("IMAGEGEN KEYCHAIN RETRY TEST PASSED")


if __name__ == "__main__":
    main()

