#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def read_text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8", errors="ignore")


def require(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise RuntimeError(f"Expected {label} to contain {needle!r}")


def main() -> None:
    readme = read_text("README.md")
    skill = read_text("SKILL.md")
    workflow = read_text("references/workflow.md")
    checklist = read_text("RELEASE_CHECKLIST.md")

    require(readme, "public OSS baseline", "README.md")
    require(readme, "Portable Local Framework Profile", "README.md")
    require(readme, "python3 scripts/doctor.py --profile codex", "README.md")
    require(readme, "python3 scripts/doctor.py --profile portable", "README.md")

    require(skill, "public OSS baseline", "SKILL.md")
    require(skill, "optional adapters", "SKILL.md")

    require(workflow, "public OSS baseline", "references/workflow.md")
    require(workflow, "optional adapters", "references/workflow.md")

    require(checklist, "doctor.py --profile codex", "RELEASE_CHECKLIST.md")
    require(checklist, "doctor.py --profile portable", "RELEASE_CHECKLIST.md")
    require(checklist, "public OSS baseline", "RELEASE_CHECKLIST.md")

    print("OSS PACKAGING DOCS TEST PASSED")


if __name__ == "__main__":
    main()
