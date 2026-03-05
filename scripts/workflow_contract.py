#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shlex
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from twyaml import dump_yaml_lite, split_frontmatter


DEFAULT_WORKFLOW_BODY = """You are operating inside a TheWorkshop autonomous execution run.

- Treat the current TheWorkshop project as the source of truth.
- Work only inside this project root and the current work item scope.
- Follow the job plan, declared outputs, acceptance criteria, and verification steps.
- Produce concrete outputs and evidence, not placeholder notes.
- If you are blocked, leave durable blocker evidence in the work item artifacts or notes.
- Do not claim completion unless TheWorkshop gates are actually satisfied.
"""


@dataclass(frozen=True)
class WorkflowContract:
    path: str
    config: dict[str, Any]
    prompt_template: str
    work_source_kind: str
    polling_interval_sec: float
    orchestration_auto_refresh: bool
    validation_require_agreement: bool
    validation_run_plan_check: bool
    dispatch_runner: str
    dispatch_max_parallel: int
    dispatch_timeout_sec: int
    dispatch_continue_on_error: bool
    dispatch_no_complete: bool
    dispatch_no_monitor: bool
    dispatch_open_policy: str
    dispatch_codex_args: list[str]
    hooks_before_cycle: str
    hooks_after_cycle: str
    hooks_timeout_sec: int

    def to_json_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["path"] = str(self.path)
        return payload


def default_workflow_frontmatter() -> dict[str, Any]:
    return {
        "work_source": {
            "kind": "local_project",
        },
        "polling": {
            "interval_sec": 30,
        },
        "orchestration": {
            "auto_refresh": True,
        },
        "validation": {
            "require_agreement": True,
            "run_plan_check": True,
        },
        "dispatch": {
            "runner": "codex",
            "max_parallel": 0,
            "timeout_sec": 0,
            "continue_on_error": False,
            "no_complete": False,
            "no_monitor": False,
            "open_policy": "once",
            "codex_args": [],
        },
        "hooks": {
            "before_cycle": "",
            "after_cycle": "",
            "timeout_sec": 60,
        },
    }


def default_workflow_text() -> str:
    frontmatter = dump_yaml_lite(default_workflow_frontmatter()).rstrip()
    body = DEFAULT_WORKFLOW_BODY.rstrip()
    return f"---\n{frontmatter}\n---\n\n{body}\n"


def workflow_path_for_project(project_root: Path, explicit_path: str | None = None) -> Path:
    if explicit_path:
        return Path(explicit_path).expanduser().resolve()
    return project_root / "WORKFLOW.md"


def load_workflow_contract(
    project_root: Path,
    *,
    workflow_path: str | None = None,
    missing_ok: bool = False,
) -> WorkflowContract | None:
    path = workflow_path_for_project(project_root, workflow_path)
    if not path.exists():
        if missing_ok:
            return None
        raise SystemExit(f"Missing WORKFLOW.md: {path}")

    doc = split_frontmatter(path.read_text(encoding="utf-8", errors="ignore"))
    config = doc.frontmatter if isinstance(doc.frontmatter, dict) else {}
    errors = validate_workflow_config(config)
    if errors:
        raise SystemExit("Invalid WORKFLOW.md:\n- " + "\n- ".join(errors))

    prompt_template = (doc.body or "").strip() or DEFAULT_WORKFLOW_BODY.strip()
    return WorkflowContract(
        path=str(path),
        config=config,
        prompt_template=prompt_template,
        work_source_kind=_work_source_kind(config),
        polling_interval_sec=_polling_interval_sec(config),
        orchestration_auto_refresh=_bool_value(config_section(config, "orchestration").get("auto_refresh"), True),
        validation_require_agreement=_bool_value(config_section(config, "validation").get("require_agreement"), True),
        validation_run_plan_check=_bool_value(config_section(config, "validation").get("run_plan_check"), True),
        dispatch_runner=_dispatch_runner(config),
        dispatch_max_parallel=_non_negative_int(config_section(config, "dispatch").get("max_parallel"), 0),
        dispatch_timeout_sec=_non_negative_int(config_section(config, "dispatch").get("timeout_sec"), 0),
        dispatch_continue_on_error=_bool_value(config_section(config, "dispatch").get("continue_on_error"), False),
        dispatch_no_complete=_bool_value(config_section(config, "dispatch").get("no_complete"), False),
        dispatch_no_monitor=_bool_value(config_section(config, "dispatch").get("no_monitor"), False),
        dispatch_open_policy=_dispatch_open_policy(config),
        dispatch_codex_args=_dispatch_codex_args(config),
        hooks_before_cycle=_string_value(config_section(config, "hooks").get("before_cycle")),
        hooks_after_cycle=_string_value(config_section(config, "hooks").get("after_cycle")),
        hooks_timeout_sec=_positive_int(config_section(config, "hooks").get("timeout_sec"), 60),
    )


def validate_workflow_config(config: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    work_source = _work_source_kind(config)
    if work_source != "local_project":
        errors.append(f"work_source.kind must be local_project, got {work_source!r}")

    interval = _float_value(config_section(config, "polling").get("interval_sec"), 30.0)
    if interval <= 0:
        errors.append("polling.interval_sec must be > 0")

    runner = _dispatch_runner(config)
    if runner not in {"codex", "none"}:
        errors.append(f"dispatch.runner must be 'codex' or 'none', got {runner!r}")

    open_policy = _dispatch_open_policy(config)
    if open_policy not in {"always", "once", "manual"}:
        errors.append(
            f"dispatch.open_policy must be one of always|once|manual, got {open_policy!r}"
        )

    max_parallel = _non_negative_int(config_section(config, "dispatch").get("max_parallel"), 0)
    if max_parallel < 0:
        errors.append("dispatch.max_parallel must be >= 0")

    hooks_timeout = _positive_int(config_section(config, "hooks").get("timeout_sec"), 60)
    if hooks_timeout <= 0:
        errors.append("hooks.timeout_sec must be > 0")

    return errors


def compose_execution_prompt(policy_prompt: str, base_prompt: str) -> str:
    policy = (policy_prompt or "").strip()
    base = (base_prompt or "").strip()
    if not policy:
        return base
    if not base:
        return policy
    return (
        f"{policy}\n\n"
        "## Current Work Item\n\n"
        f"{base}\n"
    )


def contract_snapshot_json(contract: WorkflowContract) -> str:
    return json.dumps(contract.to_json_dict(), indent=2) + "\n"


def config_section(config: dict[str, Any], key: str) -> dict[str, Any]:
    value = config.get(key)
    return value if isinstance(value, dict) else {}


def _work_source_kind(config: dict[str, Any]) -> str:
    section = config_section(config, "work_source")
    kind = _string_value(section.get("kind")).strip().lower()
    return kind or "local_project"


def _polling_interval_sec(config: dict[str, Any]) -> float:
    section = config_section(config, "polling")
    return _float_value(section.get("interval_sec"), 30.0)


def _dispatch_runner(config: dict[str, Any]) -> str:
    section = config_section(config, "dispatch")
    runner = _string_value(section.get("runner")).strip().lower()
    return runner or "codex"


def _dispatch_open_policy(config: dict[str, Any]) -> str:
    section = config_section(config, "dispatch")
    policy = _string_value(section.get("open_policy")).strip().lower()
    return policy or "once"


def _dispatch_codex_args(config: dict[str, Any]) -> list[str]:
    raw = config_section(config, "dispatch").get("codex_args")
    if isinstance(raw, list):
        out: list[str] = []
        for item in raw:
            token = _string_value(item).strip()
            if not token:
                continue
            out.append(_resolve_env_ref(token))
        return out
    if isinstance(raw, str):
        resolved = _resolve_env_ref(raw.strip())
        if not resolved:
            return []
        return [part for part in shlex.split(resolved) if part]
    return []


def _resolve_env_ref(value: str) -> str:
    if value.startswith("$") and value[1:].replace("_", "").isalnum():
        return str(os.environ.get(value[1:], "") or "").strip()
    return value


def _string_value(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return _resolve_env_ref(value).strip()
    if isinstance(value, (bool, int, float)):
        return str(value)
    return default


def _bool_value(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        token = _resolve_env_ref(value).strip().lower()
        if token in {"1", "true", "yes", "on"}:
            return True
        if token in {"0", "false", "no", "off"}:
            return False
    return default


def _float_value(value: Any, default: float) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(_resolve_env_ref(value).strip())
        except Exception:
            return default
    return default


def _non_negative_int(value: Any, default: int) -> int:
    if isinstance(value, int):
        return value if value >= 0 else default
    if isinstance(value, str):
        try:
            parsed = int(_resolve_env_ref(value).strip())
        except Exception:
            return default
        return parsed if parsed >= 0 else default
    return default


def _positive_int(value: Any, default: int) -> int:
    parsed = _non_negative_int(value, default)
    return parsed if parsed > 0 else default
