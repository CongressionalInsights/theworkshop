#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from twlib import list_job_dirs, list_workstream_dirs, normalize_str_list, now_iso, read_md, write_md
from twyaml import MarkdownDoc, YamlLiteError, split_frontmatter


@dataclass
class CmdResult:
    returncode: int
    stdout: str
    stderr: str
    cmd: list[str]


def append_section_bullet(body: str, heading: str, line: str) -> str:
    """Append a markdown bullet inside a section; create section if missing."""
    if heading not in body:
        return body.rstrip() + f"\n\n{heading}\n\n- {line}\n"

    pre, rest = body.split(heading, 1)
    rest_lines = rest.splitlines()
    insert_at = len(rest_lines)
    for i, ln in enumerate(rest_lines[1:], start=1):
        if ln.startswith("# "):
            insert_at = i
            break

    new_rest = rest_lines[:insert_at] + [f"- {line}"] + rest_lines[insert_at:]
    return (pre + heading + "\n" + "\n".join(new_rest)).rstrip() + "\n"


def extract_section(body: str, heading: str) -> str:
    lines = body.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.strip() == heading.strip():
            start = i + 1
            break
    if start is None:
        return ""

    out: list[str] = []
    for ln in lines[start:]:
        if ln.startswith("# "):
            break
        out.append(ln)
    return "\n".join(out).strip()


def extract_section_bullets(body: str, heading: str) -> list[str]:
    section = extract_section(body, heading)
    if not section:
        return []
    out: list[str] = []
    for ln in section.splitlines():
        s = ln.strip()
        if s.startswith("- "):
            val = s[2:].strip()
            if val:
                out.append(val)
    return out


def replace_section(body: str, heading: str, lines: list[str]) -> str:
    content = "\n".join(lines).rstrip()
    if heading not in body:
        return body.rstrip() + f"\n\n{heading}\n\n{content}\n"

    all_lines = body.splitlines()
    start = None
    for i, ln in enumerate(all_lines):
        if ln.strip() == heading.strip():
            start = i
            break
    if start is None:
        return body.rstrip() + f"\n\n{heading}\n\n{content}\n"

    end = len(all_lines)
    for i in range(start + 1, len(all_lines)):
        if all_lines[i].startswith("# "):
            end = i
            break

    out = all_lines[: start + 1]
    out.append("")
    out.extend(content.splitlines() if content else [])
    out.append("")
    out.extend(all_lines[end:])
    return "\n".join(out).rstrip() + "\n"


def find_job_dir(project_root: Path, wi: str) -> Path:
    matches = list(project_root.glob(f"workstreams/WS-*/jobs/{wi}-*"))
    if len(matches) != 1:
        raise SystemExit(f"Expected exactly 1 job dir for {wi}, got {len(matches)}: {matches}")
    return matches[0]


def find_workstream_dir(project_root: Path, ws_id: str) -> Path:
    for ws_dir in list_workstream_dirs(project_root):
        if ws_dir.name.startswith(ws_id):
            return ws_dir
    raise SystemExit(f"Workstream not found: {ws_id}")


def rel_project_path(project_root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_root.resolve()))
    except Exception:
        return str(path)


def parse_markdown_safe(path: Path) -> tuple[MarkdownDoc | None, str | None]:
    if not path.exists():
        return None, f"missing file: {path}"
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        return None, f"failed to read {path}: {exc}"

    try:
        return split_frontmatter(text), None
    except YamlLiteError as exc:
        return None, f"yaml parse error in {path}: {exc}"
    except Exception as exc:
        return None, f"failed to parse markdown {path}: {exc}"


def nonempty_file(path: Path) -> bool:
    try:
        return path.exists() and path.is_file() and path.stat().st_size > 0
    except Exception:
        return False


def ensure_dirs(paths: list[Path]) -> None:
    for p in paths:
        p.mkdir(parents=True, exist_ok=True)


def slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower())
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "untitled"


def infer_context_ref(project_root: Path, target_id: str) -> str:
    return rel_project_path(project_root, project_root / "notes" / "context" / f"{target_id}-CONTEXT.md")


def _parse_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    s = str(value).strip().lower()
    if s in {"1", "true", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "no", "n", "off"}:
        return False
    return default


def validate_context_gate_for_job(project_root: Path, job_plan_path: Path) -> tuple[list[str], list[str], str]:
    """
    Return (errors, warnings, context_ref).
    Context gate is enforced when context_required=true.
    """
    doc = read_md(job_plan_path)
    fm = doc.frontmatter
    wi = str(fm.get("work_item_id") or "").strip()
    context_required = _parse_bool(fm.get("context_required"), default=False)

    context_ref = str(fm.get("context_ref") or "").strip()
    if not context_ref:
        context_ref = infer_context_ref(project_root, wi)

    context_path = project_root / context_ref

    errors: list[str] = []
    warnings: list[str] = []

    if context_required:
        if not context_path.exists():
            errors.append(f"context_required=true but context file is missing: {context_ref}")
        elif not nonempty_file(context_path):
            errors.append(f"context_required=true but context file is empty: {context_ref}")
        else:
            ctx_doc, parse_err = parse_markdown_safe(context_path)
            if parse_err:
                errors.append(f"context file parse failure: {context_ref}")
            elif ctx_doc is not None:
                locked = normalize_str_list(ctx_doc.frontmatter.get("locked_decisions"))
                if not locked:
                    warnings.append(f"context file has no locked_decisions: {context_ref}")
    else:
        if str(fm.get("context_ref") or "").strip() and not context_path.exists():
            warnings.append(f"context_ref set but file missing: {context_ref}")

    return errors, warnings, context_ref


def run_script(script_name: str, argv: list[str], *, cwd: Path | None = None, check: bool = True) -> CmdResult:
    scripts_dir = Path(__file__).resolve().parent
    cmd = [sys.executable, str(scripts_dir / script_name)] + argv
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, capture_output=True)
    result = CmdResult(returncode=int(proc.returncode), stdout=proc.stdout or "", stderr=proc.stderr or "", cmd=cmd)
    if check and result.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            f"  cmd={' '.join(result.cmd)}\n"
            f"  exit={result.returncode}\n"
            f"  stdout:\n{result.stdout}\n"
            f"  stderr:\n{result.stderr}\n"
        )
    return result


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def merge_unique(existing: list[str], additions: list[str]) -> list[str]:
    out = [str(x).strip() for x in existing if str(x).strip()]
    seen = set(out)
    for x in additions:
        s = str(x).strip()
        if not s or s in seen:
            continue
        out.append(s)
        seen.add(s)
    return out


def next_counter_id(prefix: str, date_yyyymmdd: str, existing_names: list[str]) -> str:
    pattern = re.compile(rf"^{re.escape(prefix)}-{re.escape(date_yyyymmdd)}-(\d{{3}})")
    max_n = 0
    for name in existing_names:
        m = pattern.match(name)
        if not m:
            continue
        try:
            max_n = max(max_n, int(m.group(1)))
        except Exception:
            continue
    return f"{prefix}-{date_yyyymmdd}-{max_n + 1:03d}"


def update_frontmatter(path: Path, updates: dict[str, Any]) -> MarkdownDoc:
    doc = read_md(path)
    for k, v in updates.items():
        doc.frontmatter[k] = v
    doc.frontmatter["updated_at"] = now_iso()
    write_md(path, doc)
    return doc


def rollup_status(states: list[str]) -> str:
    """Canonical status rollup used across project/workstream views."""
    if any(s == "in_progress" for s in states):
        return "in_progress"
    if any(s == "blocked" for s in states):
        return "blocked"
    if states and all(s in {"done", "cancelled"} for s in states):
        return "done"
    return "planned"


def verify_summary_file(path: Path, required_markers: list[str] | None = None) -> tuple[bool, list[str]]:
    """
    Lightweight summary verification helper.
    Returns (ok, issues).
    """
    markers = required_markers or ["# ", "Summary"]
    issues: list[str] = []
    if not path.exists():
        return False, [f"missing summary file: {path}"]
    if not nonempty_file(path):
        return False, [f"summary file is empty: {path}"]
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        return False, [f"failed to read summary file: {exc}"]
    for marker in markers:
        if marker not in text:
            issues.append(f"missing marker in summary: {marker!r}")
    return len(issues) == 0, issues
