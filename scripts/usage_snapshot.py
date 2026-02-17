#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from twlib import build_token_cost_payload, now_iso, parse_time, read_md, resolve_project_root


def wall_elapsed(started_at: str) -> float | None:
    dt = parse_time(started_at or "")
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds()


def exec_log_time(project_root: Path) -> float:
    path = project_root / "logs" / "execution.jsonl"
    if not path.exists():
        return 0.0
    total = 0.0
    for ln in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not ln.strip():
            continue
        try:
            obj = json.loads(ln)
        except Exception:
            continue
        try:
            total += float(obj.get("duration_sec") or 0)
        except Exception:
            pass
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="Usage snapshot for TheWorkshop (tokens/time).")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--out", help="Output JSON path (default: outputs/usage.json)")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    proj_doc = read_md(project_root / "plan.md")
    started_at = str(proj_doc.frontmatter.get("started_at") or "")

    tokens_payload = build_token_cost_payload(project_root, "codex")

    payload = {
        "schema": "theworkshop.usage.v1",
        "generated_at": now_iso(),
        "project": str(project_root),
        "wall_elapsed_sec": wall_elapsed(started_at),
        "execution_logged_sec": exec_log_time(project_root),
        "tokens": tokens_payload,
    }

    out_dir = project_root / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out).expanduser().resolve() if args.out else out_dir / "usage.json"
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(str(out_path))


if __name__ == "__main__":
    main()
