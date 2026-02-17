#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


SCRIPTS_DIR = Path(__file__).resolve().parent


def py(script: str) -> list[str]:
    return [sys.executable, str(SCRIPTS_DIR / script)]


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["THEWORKSHOP_NO_OPEN"] = "1"
    env["THEWORKSHOP_NO_MONITOR"] = "1"
    env["THEWORKSHOP_NO_KEYCHAIN"] = "1"
    proc = subprocess.run(cmd, text=True, capture_output=True, env=env)
    if check and proc.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            f"  cmd={' '.join(cmd)}\n"
            f"  exit={proc.returncode}\n"
            f"  stdout:\n{proc.stdout}\n"
            f"  stderr:\n{proc.stderr}\n"
        )
    return proc


def normalize_group(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, dict):
        for key in ("jobs", "work_items", "items", "members", "nodes", "ids"):
            maybe = value.get(key)
            if isinstance(maybe, list):
                out = [str(v).strip() for v in maybe if str(v).strip()]
                if out:
                    return out
        single = str(value.get("id") or value.get("work_item_id") or "").strip()
        return [single] if single else []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    return []


def extract_groups(payload: dict[str, Any]) -> list[list[str]]:
    group_source: Any = None
    for key in ("parallel_groups", "groups", "execution_groups", "batches", "waves"):
        if key in payload:
            group_source = payload.get(key)
            break
    if group_source is None and isinstance(payload.get("orchestration"), dict):
        nested = payload["orchestration"]
        for key in ("parallel_groups", "groups", "execution_groups", "batches", "waves"):
            if key in nested:
                group_source = nested.get(key)
                break
    if not isinstance(group_source, list):
        return []
    out: list[list[str]] = []
    for item in group_source:
        group = normalize_group(item)
        if group:
            out.append(group)
    return out


def extract_critical_path(payload: dict[str, Any]) -> list[str]:
    candidate: Any = None
    for key in ("critical_path", "criticalPath", "critical_path_jobs"):
        if key in payload:
            candidate = payload.get(key)
            break
    if candidate is None and isinstance(payload.get("summary"), dict):
        summary = payload["summary"]
        for key in ("critical_path", "criticalPath", "critical_path_jobs"):
            if key in summary:
                candidate = summary.get(key)
                break
    if isinstance(candidate, dict):
        for key in ("jobs", "work_items", "items", "nodes", "ids"):
            maybe = candidate.get(key)
            if isinstance(maybe, list):
                return [str(v).strip() for v in maybe if str(v).strip()]
        return []
    if isinstance(candidate, list):
        return [str(v).strip() for v in candidate if str(v).strip()]
    if isinstance(candidate, str):
        text = candidate.strip()
        return [text] if text else []
    return []


def main() -> None:
    orchestrate_script = SCRIPTS_DIR / "orchestrate_plan.py"
    if not orchestrate_script.exists():
        raise RuntimeError(f"Missing script under test: {orchestrate_script}")

    with tempfile.TemporaryDirectory(prefix="theworkshop-orchestrate-") as td:
        base_dir = Path(td).resolve()

        project_root = Path(
            run(py("project_new.py") + ["--name", "Orchestrate Plan Test", "--base-dir", str(base_dir)]).stdout.strip()
        ).resolve()
        ws_id = run(py("workstream_add.py") + ["--project", str(project_root), "--title", "Main Workstream"]).stdout.strip()

        wi_a = run(
            py("job_add.py")
            + [
                "--project",
                str(project_root),
                "--workstream",
                ws_id,
                "--title",
                "A: bootstrap",
                "--estimate-hours",
                "1.0",
            ]
        ).stdout.strip()
        wi_b = run(
            py("job_add.py")
            + [
                "--project",
                str(project_root),
                "--workstream",
                ws_id,
                "--title",
                "B: branch short",
                "--depends-on",
                wi_a,
                "--estimate-hours",
                "1.0",
            ]
        ).stdout.strip()
        wi_c = run(
            py("job_add.py")
            + [
                "--project",
                str(project_root),
                "--workstream",
                ws_id,
                "--title",
                "C: branch long",
                "--depends-on",
                wi_a,
                "--estimate-hours",
                "3.0",
            ]
        ).stdout.strip()
        wi_d = run(
            py("job_add.py")
            + [
                "--project",
                str(project_root),
                "--workstream",
                ws_id,
                "--title",
                "D: merge",
                "--depends-on",
                wi_b,
                "--depends-on",
                wi_c,
                "--estimate-hours",
                "1.0",
            ]
        ).stdout.strip()

        run(py("orchestrate_plan.py") + ["--project", str(project_root)])

        out_path = project_root / "outputs" / "orchestration.json"
        if not out_path.exists():
            raise RuntimeError(f"Expected orchestration output missing: {out_path}")
        payload = json.loads(out_path.read_text(encoding="utf-8"))
        if "parallel_groups" not in payload:
            raise RuntimeError(f"Expected compatibility key `parallel_groups` in payload: {out_path}")

        groups = extract_groups(payload)
        expected_groups = [[wi_a], [wi_b, wi_c], [wi_d]]
        normalized_groups = [sorted(g) for g in groups]
        normalized_expected = [sorted(g) for g in expected_groups]
        if normalized_groups != normalized_expected:
            raise RuntimeError(
                "Unexpected parallel groups.\n"
                f"  expected={normalized_expected}\n"
                f"  actual={normalized_groups}\n"
                f"  payload_path={out_path}"
            )

        critical_path = extract_critical_path(payload)
        expected_path = [wi_a, wi_c, wi_d]
        if critical_path != expected_path:
            raise RuntimeError(
                "Unexpected critical path.\n"
                f"  expected={expected_path}\n"
                f"  actual={critical_path}\n"
                f"  payload_path={out_path}"
            )

        print("ORCHESTRATE PLAN TEST PASSED")
        print(str(project_root))


if __name__ == "__main__":
    main()
