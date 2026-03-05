#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from twlib import resolve_project_root
from workflow_contract import contract_snapshot_json, load_workflow_contract


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate and print the effective TheWorkshop WORKFLOW.md contract.")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--workflow", help="Explicit WORKFLOW.md path")
    parser.add_argument("--json", action="store_true", help="Print JSON only")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    contract = load_workflow_contract(project_root, workflow_path=args.workflow)
    assert contract is not None

    if args.json:
        print(contract_snapshot_json(contract), end="")
        return

    payload = contract.to_json_dict()
    print(f"workflow: {payload['path']}")
    print(f"work_source.kind: {payload['work_source_kind']}")
    print(f"polling.interval_sec: {payload['polling_interval_sec']}")
    print(f"dispatch.runner: {payload['dispatch_runner']}")
    print(f"dispatch.max_parallel: {payload['dispatch_max_parallel']}")
    print(f"dispatch.open_policy: {payload['dispatch_open_policy']}")
    print(f"dispatch.codex_args: {json.dumps(payload['dispatch_codex_args'])}")


if __name__ == "__main__":
    main()
