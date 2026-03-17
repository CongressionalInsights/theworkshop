#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from twlib import now_iso, read_md, resolve_project_root, write_md


LEGACY_PROFILE_MAP = {
    "default": "theworkshop_worker",
    "worker": "theworkshop_worker",
    "implementer": "theworkshop_worker",
    "builder": "theworkshop_worker",
    "explorer": "theworkshop_explorer",
    "research": "theworkshop_explorer",
    "investigate": "theworkshop_explorer",
    "analysis": "theworkshop_explorer",
    "review": "theworkshop_reviewer",
    "reviewer": "theworkshop_reviewer",
    "qa": "theworkshop_reviewer",
    "verify": "theworkshop_reviewer",
    "closeout": "theworkshop_reviewer",
}


def _job_plan_paths(project_root: Path) -> list[Path]:
    return sorted(project_root.glob("workstreams/WS-*/jobs/WI-*/plan.md"))


def _canonical_profile(doc) -> str:
    fm = doc.frontmatter
    explicit = str(fm.get("agent_profile") or "").strip().lower()
    if explicit:
        return LEGACY_PROFILE_MAP.get(explicit, explicit)

    mode = str(fm.get("orchestration_mode") or "").strip().lower()
    if mode in {"review", "verify", "qa", "closeout"}:
        return "theworkshop_reviewer"
    if mode in {"investigate", "research", "analyze", "analysis"}:
        return "theworkshop_explorer"

    hint = str(fm.get("agent_type_hint") or "").strip().lower()
    if hint:
        return LEGACY_PROFILE_MAP.get(hint, "theworkshop_worker")

    stakes = str(fm.get("stakes") or "").strip().lower()
    if stakes in {"critical", "high"}:
        return "theworkshop_reviewer"

    return "theworkshop_worker"


def main() -> None:
    parser = argparse.ArgumentParser(description="Normalize TheWorkshop job agent profiles to canonical names.")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--write", action="store_true", help="Write normalized frontmatter back to job plans")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    changes: list[dict[str, str]] = []
    for path in _job_plan_paths(project_root):
        doc = read_md(path)
        fm = doc.frontmatter
        before_profile = str(fm.get("agent_profile") or "")
        before_hint = str(fm.get("agent_type_hint") or "")
        canonical = _canonical_profile(doc)
        changed = False

        if canonical and before_profile != canonical:
            fm["agent_profile"] = canonical
            changed = True
        if "agent_type_hint" in fm:
            del fm["agent_type_hint"]
            changed = True

        if changed:
            fm["updated_at"] = now_iso()
            if args.write:
                write_md(path, doc)
            changes.append(
                {
                    "path": str(path),
                    "before_agent_profile": before_profile,
                    "before_agent_type_hint": before_hint,
                    "after_agent_profile": canonical,
                    "removed_agent_type_hint": str(before_hint != ""),
                }
            )

    payload = {
        "schema": "theworkshop.agent-profile-normalization.v1",
        "project": str(project_root),
        "write": bool(args.write),
        "changes": changes,
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
