#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from twlib import now_iso, resolve_project_root


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
SCHEMA_DIR = SKILL_ROOT / "schemas"

TARGETS = {
    "orchestration": {
        "data": Path("outputs/orchestration.json"),
        "schema": SCHEMA_DIR / "orchestration.schema.json",
    },
    "dashboard": {
        "data": Path("outputs/dashboard.json"),
        "schema": SCHEMA_DIR / "dashboard.schema.json",
    },
    "truth": {
        "data": Path("outputs/truth-report.json"),
        "schema": SCHEMA_DIR / "truth-report.schema.json",
    },
    "rewards": {
        "data": Path("outputs/rewards.json"),
        "schema": SCHEMA_DIR / "rewards.schema.json",
    },
    "orchestration-execution": {
        "data": Path("outputs/orchestration-execution.json"),
        "schema": SCHEMA_DIR / "orchestration-execution.schema.json",
    },
    "council": {
        "data": Path("outputs/council/council-plan.json"),
        "schema": SCHEMA_DIR / "council-plan.schema.json",
    },
}


JSON_TYPE_TO_PY = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "null": type(None),
}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_type(value: Any, expected: str) -> bool:
    py_type = JSON_TYPE_TO_PY.get(expected)
    if py_type is None:
        return True
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, py_type)


def _fallback_validate(data: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    errs: list[str] = []

    schema_type = schema.get("type")
    if isinstance(schema_type, str) and not _validate_type(data, schema_type):
        return [f"{path}: expected {schema_type}, got {type(data).__name__}"]

    required = schema.get("required")
    if isinstance(required, list) and isinstance(data, dict):
        for key in required:
            if str(key) not in data:
                errs.append(f"{path}: missing required key '{key}'")

    if isinstance(data, dict):
        props = schema.get("properties")
        if isinstance(props, dict):
            for key, sub in props.items():
                if key not in data:
                    continue
                if isinstance(sub, dict):
                    errs.extend(_fallback_validate(data[key], sub, f"{path}.{key}"))

    if isinstance(data, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for idx, item in enumerate(data):
                errs.extend(_fallback_validate(item, item_schema, f"{path}[{idx}]"))

    return errs


def _validate_with_jsonschema(data: Any, schema: dict[str, Any]) -> list[str] | None:
    try:
        import jsonschema  # type: ignore
    except Exception:
        return None

    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    out: list[str] = []
    for err in errors:
        loc = "$"
        if err.path:
            loc = "$." + ".".join(str(p) for p in err.path)
        out.append(f"{loc}: {err.message}")
    return out


def _validate_target(project_root: Path, name: str, strict_missing: bool) -> dict[str, Any]:
    meta = TARGETS[name]
    data_path = project_root / meta["data"]
    schema_path = meta["schema"]

    result: dict[str, Any] = {
        "target": name,
        "data_path": str(data_path),
        "schema_path": str(schema_path),
        "present": data_path.exists(),
        "valid": True,
        "errors": [],
    }

    if not schema_path.exists():
        result["valid"] = False
        result["errors"] = [f"schema missing: {schema_path}"]
        return result

    if not data_path.exists():
        if strict_missing:
            result["valid"] = False
            result["errors"] = [f"missing artifact: {data_path}"]
        return result

    try:
        data = _load_json(data_path)
    except Exception as exc:
        result["valid"] = False
        result["errors"] = [f"failed to parse data JSON: {exc}"]
        return result

    try:
        schema = _load_json(schema_path)
    except Exception as exc:
        result["valid"] = False
        result["errors"] = [f"failed to parse schema JSON: {exc}"]
        return result

    errors = _validate_with_jsonschema(data, schema)
    engine = "jsonschema"
    if errors is None:
        errors = _fallback_validate(data, schema)
        engine = "fallback"

    result["engine"] = engine
    result["errors"] = errors
    result["valid"] = len(errors) == 0
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate TheWorkshop JSON artifacts against schemas.")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument(
        "--target",
        action="append",
        choices=sorted(TARGETS.keys()),
        help="Specific target to validate (repeatable); default validates all targets.",
    )
    parser.add_argument("--strict-missing", action="store_true", help="Fail when target artifact is missing.")
    parser.add_argument("--out", help="Write result JSON path (default: outputs/schema-validation.json)")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    default_targets = [name for name in TARGETS.keys() if name != "council"]
    targets = args.target or default_targets
    results = [_validate_target(project_root, name, bool(args.strict_missing)) for name in targets]

    payload = {
        "schema": "theworkshop.schema-validation.v1",
        "generated_at": now_iso(),
        "project": str(project_root),
        "targets": results,
        "all_valid": all(bool(item.get("valid")) for item in results),
    }

    out_path = Path(args.out).expanduser().resolve() if args.out else (project_root / "outputs" / "schema-validation.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    for item in results:
        status = "OK" if item.get("valid") else "ERROR"
        print(f"[{status}] {item['target']} -> {item['data_path']}")
        for err in item.get("errors") or []:
            print(f"  - {err}")

    if not payload["all_valid"]:
        raise SystemExit(1)

    print(str(out_path))


if __name__ == "__main__":
    main()
