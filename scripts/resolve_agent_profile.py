#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from twlib import now_iso, read_md, resolve_project_root, write_md


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
DEFAULT_REGISTRY_DIR = SKILL_ROOT / "references" / "agents"

ALIAS_TO_PROFILE = {
    "default": "worker",
    "worker": "worker",
    "implementer": "worker",
    "builder": "worker",
    "explorer": "explorer",
    "research": "explorer",
    "investigate": "explorer",
    "analysis": "explorer",
    "review": "reviewer",
    "reviewer": "reviewer",
    "qa": "reviewer",
    "verify": "reviewer",
    "closeout": "reviewer",
}


def _json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def _load_registry() -> dict[str, dict[str, Any]]:
    registry: dict[str, dict[str, Any]] = {}
    if not DEFAULT_REGISTRY_DIR.exists():
        return registry
    for path in sorted(DEFAULT_REGISTRY_DIR.glob("*.json")):
        payload = _json_file(path)
        name = str(payload.get("name") or path.stem).strip().lower()
        if not name:
            continue
        payload.setdefault("name", name)
        payload["_path"] = str(path)
        registry[name] = payload
    return registry


def _find_job_plan(project_root: Path, wi: str) -> Path:
    matches = list(project_root.glob(f"workstreams/WS-*/jobs/{wi}-*/plan.md"))
    if len(matches) != 1:
        raise SystemExit(f"Expected exactly 1 job plan for {wi}, got {len(matches)}: {matches}")
    return matches[0]


def _profile_from_mode(mode: str) -> str:
    token = (mode or "").strip().lower()
    if token in {"review", "verify", "qa", "closeout"}:
        return "reviewer"
    if token in {"investigate", "research", "analyze", "analysis"}:
        return "explorer"
    return "worker"


def _resolve_profile_name(frontmatter: dict[str, Any], registry: dict[str, dict[str, Any]]) -> tuple[str, str]:
    explicit = str(frontmatter.get("agent_profile") or "").strip().lower()
    if explicit and explicit in registry:
        return explicit, f"frontmatter.agent_profile={explicit}"

    mode = str(frontmatter.get("orchestration_mode") or "").strip().lower()
    mode_profile = _profile_from_mode(mode)
    if mode_profile in registry and mode:
        return mode_profile, f"frontmatter.orchestration_mode={mode}"

    hint = str(frontmatter.get("agent_type_hint") or "").strip().lower()
    if hint:
        hinted = ALIAS_TO_PROFILE.get(hint, hint)
        if hinted in registry:
            return hinted, f"frontmatter.agent_type_hint={hint}"

    stakes = str(frontmatter.get("stakes") or "").strip().lower()
    if stakes in {"critical", "high"} and "reviewer" in registry:
        return "reviewer", f"stakes={stakes}"
    if stakes in {"low", "normal"} and "worker" in registry:
        return "worker", f"stakes={stakes}"

    if "worker" in registry:
        return "worker", "fallback worker"

    if registry:
        first = sorted(registry.keys())[0]
        return first, f"fallback first profile={first}"

    return "", "no profile registry found"


def _execution_defaults(profile: dict[str, Any]) -> tuple[int, int]:
    execution = profile.get("execution") if isinstance(profile.get("execution"), dict) else {}
    budget = int(execution.get("default_dispatch_budget") or 1)
    retry = int(execution.get("default_retry_limit") or 1)
    if budget <= 0:
        budget = 1
    if retry < 0:
        retry = 0
    return budget, retry


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve TheWorkshop agent profile for a work item.")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--work-item-id", required=True, help="WI-...")
    parser.add_argument("--write", action="store_true", help="Write resolved profile fields back to job frontmatter")
    parser.add_argument("--out", help="Write JSON resolution payload path")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    plan_path = _find_job_plan(project_root, args.work_item_id.strip())
    doc = read_md(plan_path)
    fm = doc.frontmatter

    registry = _load_registry()
    profile_name, resolution_reason = _resolve_profile_name(fm, registry)
    profile = registry.get(profile_name) if profile_name else {}
    dispatch_budget, retry_limit = _execution_defaults(profile or {})

    payload = {
        "schema": "theworkshop.agent-resolution.v1",
        "generated_at": now_iso(),
        "project": str(project_root),
        "work_item_id": str(fm.get("work_item_id") or ""),
        "stakes": str(fm.get("stakes") or ""),
        "agent_type_hint": str(fm.get("agent_type_hint") or ""),
        "orchestration_mode": str(fm.get("orchestration_mode") or ""),
        "parallel_group": str(fm.get("parallel_group") or ""),
        "resolved_profile": profile_name,
        "resolution_reason": resolution_reason,
        "dispatch_budget": int(fm.get("dispatch_budget") or dispatch_budget),
        "retry_limit": int(fm.get("retry_limit") or retry_limit),
        "profile": profile or {},
        "registry_size": len(registry),
    }

    if args.write:
        if profile_name:
            fm["agent_profile"] = profile_name
        if not str(fm.get("agent_type_hint") or "").strip() and profile_name:
            fm["agent_type_hint"] = str((profile.get("agent_type") or "worker"))
        if fm.get("dispatch_budget") is None:
            fm["dispatch_budget"] = int(dispatch_budget)
        if fm.get("retry_limit") is None:
            fm["retry_limit"] = int(retry_limit)
        fm["updated_at"] = now_iso()
        write_md(plan_path, doc)

    if args.out:
        out_path = Path(args.out).expanduser().resolve()
    else:
        out_path = plan_path.parent / "artifacts" / "agent-profile.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
