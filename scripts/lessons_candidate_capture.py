#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from learning_store import create_lesson_candidate, parse_csv, unique_values
from twlib import resolve_project_root


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture a staged lesson candidate for later curation.")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--work-item-id", default="", help="Related WI-... identifier")
    parser.add_argument("--source-agent", default="", help="Agent/runtime name proposing the lesson")
    parser.add_argument("--agent-id", default="", help="Logical agent-run identifier for scoped curation")
    parser.add_argument("--tags", default="", help="Comma-separated tags")
    parser.add_argument("--linked", default="", help="Comma-separated linked IDs")
    parser.add_argument("--context", required=True, help="What happened")
    parser.add_argument("--worked", required=True, help="What worked")
    parser.add_argument("--failed", default="", help="What failed")
    parser.add_argument("--recommendation", required=True, help="What to do next time")
    parser.add_argument("--confidence", type=float, default=0.7, help="Confidence 0..1")
    parser.add_argument("--loop-attempt", type=int, default=0, help="Loop attempt number when captured from a loop")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    linked = parse_csv(args.linked)
    if args.work_item_id.strip():
        linked = unique_values(linked + [args.work_item_id.strip()])
    payload = create_lesson_candidate(
        project_root,
        source_agent=args.source_agent,
        agent_id=args.agent_id,
        tags=parse_csv(args.tags),
        linked=linked,
        context=args.context,
        worked=args.worked,
        failed=args.failed,
        recommendation=args.recommendation,
        confidence=float(args.confidence),
        work_item_id=args.work_item_id,
        loop_attempt=int(args.loop_attempt or 0),
    )
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
