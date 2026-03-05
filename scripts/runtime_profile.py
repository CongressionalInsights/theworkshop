#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Mapping

from twlib import codex_home


DOCTOR_PROFILES = {"codex", "portable"}


def resolve_doctor_profile(value: str) -> str:
    token = str(value or "").strip().lower()
    if token in DOCTOR_PROFILES:
        return token
    return "codex"


def command_available(name: str) -> bool:
    return bool(shutil.which(name))


def skill_script_path(skill_name: str, relative_path: str, env: Mapping[str, str] | None = None) -> Path:
    env_root = dict(os.environ) if env is None else dict(env)
    override = env_root.get("CODEX_HOME", "").strip()
    base = Path(override).expanduser() if override else codex_home()
    return base / "skills" / skill_name / Path(relative_path)


def session_logs_exist(session_id: str, root: Path) -> bool:
    if not session_id:
        return False
    sessions = root / "sessions"
    if not sessions.exists():
        return False
    try:
        return any(session_id in p.name for p in sessions.rglob("rollout-*.jsonl"))
    except Exception:
        return False
