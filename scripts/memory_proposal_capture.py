#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json

from learning_store import MEMORY_KIND_CHOICES, MEMORY_SCOPE_CHOICES, create_memory_proposal
from twlib import resolve_project_root


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture a staged durable-memory proposal for later curation.")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--work-item-id", default="", help="Related WI-... identifier")
    parser.add_argument("--source-agent", default="", help="Agent/runtime name proposing the memory")
    parser.add_argument("--agent-id", default="", help="Logical agent-run identifier for scoped curation")
    parser.add_argument("--scope", choices=sorted(MEMORY_SCOPE_CHOICES), default="project", help="Memory scope")
    parser.add_argument("--kind", choices=sorted(MEMORY_KIND_CHOICES), required=True, help="Durable memory kind")
    parser.add_argument("--statement", required=True, help="Concise durable memory statement")
    parser.add_argument("--evidence", action="append", default=[], help="Brief supporting evidence (repeatable)")
    parser.add_argument("--confidence", type=float, default=0.7, help="Confidence 0..1")
    parser.add_argument("--promote-reason", default="", help="Why this should persist as durable memory")
    parser.add_argument("--loop-attempt", type=int, default=0, help="Loop attempt number when captured from a loop")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    payload = create_memory_proposal(
        project_root,
        source_agent=args.source_agent,
        agent_id=args.agent_id,
        scope=args.scope,
        kind=args.kind,
        statement=args.statement,
        evidence=list(args.evidence or []),
        confidence=float(args.confidence),
        promote_reason=args.promote_reason,
        work_item_id=args.work_item_id,
        loop_attempt=int(args.loop_attempt or 0),
    )
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
