#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as fp:
            data = tomllib.load(fp)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _trusted_projects(config: dict[str, Any]) -> list[Path]:
    projects = config.get("projects")
    out: list[Path] = []
    if not isinstance(projects, dict):
        return out
    for raw_path, payload in projects.items():
        trust = ""
        if isinstance(payload, dict):
            trust = str(payload.get("trust_level") or "").strip().lower()
        if trust == "trusted":
            out.append(Path(str(raw_path)).expanduser().resolve())
    return sorted(set(out))


def _agent_names(agent_dir: Path) -> list[str]:
    names: list[str] = []
    for path in sorted(agent_dir.glob("*.toml")):
        payload = _load_toml(path)
        name = str(payload.get("name") or path.stem).strip()
        if name:
            names.append(name)
    return names


def _project_record(project_root: Path, user_agent_names: set[str]) -> dict[str, Any]:
    project_cfg = project_root / ".codex" / "config.toml"
    agent_dir = project_root / ".codex" / "agents"
    cfg = _load_toml(project_cfg)
    agents_cfg = cfg.get("agents") if isinstance(cfg.get("agents"), dict) else {}
    project_agent_names = _agent_names(agent_dir) if agent_dir.exists() else []
    conflicts = sorted(name for name in project_agent_names if name in user_agent_names)
    return {
        "project": str(project_root),
        "has_project_config": project_cfg.exists(),
        "project_config_path": str(project_cfg),
        "has_project_agents": agent_dir.exists(),
        "project_agents_path": str(agent_dir),
        "custom_agent_names": project_agent_names,
        "agent_settings": {
            "max_threads": agents_cfg.get("max_threads"),
            "max_depth": agents_cfg.get("max_depth"),
            "job_max_runtime_seconds": agents_cfg.get("job_max_runtime_seconds"),
        },
        "name_conflicts_with_global_agents": conflicts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Inventory Codex agent/config surfaces across trusted projects.")
    parser.add_argument("--codex-config", default="~/.codex/config.toml", help="Path to user Codex config.toml")
    parser.add_argument("--project", action="append", default=[], help="Explicit project root(s) to include")
    parser.add_argument("--out", help="Optional JSON output path")
    args = parser.parse_args()

    codex_config_path = Path(args.codex_config).expanduser().resolve()
    user_cfg = _load_toml(codex_config_path)
    global_agent_dir = codex_config_path.parent / "agents"
    global_agent_names = set(_agent_names(global_agent_dir)) if global_agent_dir.exists() else set()

    project_roots = _trusted_projects(user_cfg)
    for raw in args.project:
        project_roots.append(Path(raw).expanduser().resolve())
    home_root = codex_config_path.parent.parent.resolve()
    project_roots = sorted(path for path in set(project_roots) if path != home_root)

    payload = {
        "schema": "theworkshop.agent-surface-inventory.v1",
        "codex_config_path": str(codex_config_path),
        "global_agent_dir": str(global_agent_dir),
        "has_global_agent_dir": global_agent_dir.exists(),
        "global_agent_names": sorted(global_agent_names),
        "projects": [_project_record(path, global_agent_names) for path in project_roots],
    }

    text = json.dumps(payload, indent=2) + "\n"
    if args.out:
        out_path = Path(args.out).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
