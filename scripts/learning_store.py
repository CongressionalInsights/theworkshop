from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

from twlib import codex_home, ensure_dir, next_id, now_iso, read_md, today_iso_date, today_yyyymmdd


MEMORY_PROPOSAL_SCHEMA = "theworkshop.memory-proposal.v1"
MEMORY_CURATION_SCHEMA = "theworkshop.memory-curation.v1"
LESSON_CANDIDATE_SCHEMA = "theworkshop.lesson-candidate.v1"
LESSON_CURATION_SCHEMA = "theworkshop.lesson-curation.v1"

MEMORY_PROPOSAL_PREFIX = "MP"
LESSON_CANDIDATE_PREFIX = "LC"

MEMORY_KIND_CHOICES = {"workflow", "decision", "pitfall", "follow_up"}
MEMORY_SCOPE_CHOICES = {"project", "global"}
MEMORY_SECTION_TITLES = {
    "workflow": "Workflow",
    "decision": "Decisions",
    "pitfall": "Pitfalls",
    "follow_up": "Follow Up",
}

SCRIPT_DIR = Path(__file__).resolve().parent


def load_json_dict(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json_dict(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def memory_proposals_dir(project_root: Path) -> Path:
    return project_root / ".theworkshop" / "memory-proposals"


def lesson_candidates_dir(project_root: Path) -> Path:
    return project_root / ".theworkshop" / "lessons-candidates"


def _existing_ids(dir_path: Path, prefix: str, date: str) -> list[str]:
    out: list[str] = []
    if not dir_path.exists():
        return out
    for path in sorted(dir_path.glob("*.json")):
        payload = load_json_dict(path)
        ident = str(payload.get("id") or "").strip()
        if ident.startswith(f"{prefix}-{date}-"):
            out.append(ident)
    return out


def next_staged_id(dir_path: Path, prefix: str) -> str:
    date = today_yyyymmdd()
    return next_id(prefix, date, _existing_ids(dir_path, prefix, date))


def project_title(project_root: Path) -> str:
    plan_path = project_root / "plan.md"
    if plan_path.exists():
        title = str(read_md(plan_path).frontmatter.get("title") or "").strip()
        if title:
            return title
    return project_root.name.strip() or "Project"


def _memory_filename(project_root: Path) -> str:
    title = project_title(project_root)
    token = re.sub(r"[^A-Za-z0-9]+", "", title).strip()
    return token or "Project"


def project_memory_path(project_root: Path) -> Path:
    return codex_home() / "memories" / "projects" / f"{_memory_filename(project_root)}.md"


def global_memory_path() -> Path:
    return codex_home() / "memories" / "global.md"


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def unique_values(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        token = str(item or "").strip()
        if not token:
            continue
        key = normalize_text(token)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(token)
    return out


def parse_csv(value: str) -> list[str]:
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def iter_staged_records(
    dir_path: Path,
    *,
    schema: str,
    work_item_id: str = "",
    status: str = "",
    agent_id: str = "",
    loop_attempt: int | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not dir_path.exists():
        return out

    work_item_norm = str(work_item_id or "").strip()
    status_norm = str(status or "").strip().lower()
    agent_id_norm = str(agent_id or "").strip()
    for path in sorted(dir_path.glob("*.json")):
        payload = load_json_dict(path)
        if str(payload.get("schema") or "").strip() != schema:
            continue
        if work_item_norm and str(payload.get("work_item_id") or "").strip() != work_item_norm:
            continue
        if status_norm and str(payload.get("status") or "").strip().lower() != status_norm:
            continue
        if agent_id_norm and str(payload.get("agent_id") or "").strip() != agent_id_norm:
            continue
        if loop_attempt is not None and int(payload.get("loop_attempt") or 0) != int(loop_attempt):
            continue
        payload["_path"] = str(path)
        out.append(payload)
    return out


def create_memory_proposal(
    project_root: Path,
    *,
    source_agent: str,
    agent_id: str = "",
    scope: str,
    kind: str,
    statement: str,
    evidence: list[str],
    confidence: float,
    promote_reason: str,
    work_item_id: str = "",
    loop_attempt: int = 0,
) -> dict[str, Any]:
    proposal_dir = memory_proposals_dir(project_root)
    ensure_dir(proposal_dir)
    ident = next_staged_id(proposal_dir, MEMORY_PROPOSAL_PREFIX)
    payload = {
        "schema": MEMORY_PROPOSAL_SCHEMA,
        "id": ident,
        "status": "proposed",
        "captured_at": now_iso(),
        "project": str(project_root),
        "project_title": project_title(project_root),
        "work_item_id": str(work_item_id or "").strip(),
        "agent_id": str(agent_id or "").strip(),
        "loop_attempt": int(loop_attempt or 0),
        "source_agent": str(source_agent or "").strip() or "unknown",
        "scope": str(scope or "").strip().lower(),
        "kind": str(kind or "").strip().lower(),
        "statement": " ".join(str(statement or "").strip().split()),
        "evidence": unique_values(evidence),
        "confidence": round(max(0.0, min(1.0, float(confidence))), 3),
        "promote_reason": " ".join(str(promote_reason or "").strip().split()),
    }
    out_path = proposal_dir / f"{ident}.json"
    write_json_dict(out_path, payload)
    payload["_path"] = str(out_path)
    return payload


def create_lesson_candidate(
    project_root: Path,
    *,
    source_agent: str,
    agent_id: str = "",
    tags: list[str],
    linked: list[str],
    context: str,
    worked: str,
    failed: str,
    recommendation: str,
    confidence: float,
    work_item_id: str = "",
    loop_attempt: int = 0,
) -> dict[str, Any]:
    candidate_dir = lesson_candidates_dir(project_root)
    ensure_dir(candidate_dir)
    ident = next_staged_id(candidate_dir, LESSON_CANDIDATE_PREFIX)
    payload = {
        "schema": LESSON_CANDIDATE_SCHEMA,
        "id": ident,
        "status": "proposed",
        "captured_at": now_iso(),
        "project": str(project_root),
        "project_title": project_title(project_root),
        "work_item_id": str(work_item_id or "").strip(),
        "agent_id": str(agent_id or "").strip(),
        "loop_attempt": int(loop_attempt or 0),
        "source_agent": str(source_agent or "").strip() or "unknown",
        "tags": unique_values(tags),
        "linked": unique_values(linked),
        "context": " ".join(str(context or "").strip().split()),
        "worked": " ".join(str(worked or "").strip().split()),
        "failed": " ".join(str(failed or "").strip().split()),
        "recommendation": " ".join(str(recommendation or "").strip().split()),
        "confidence": round(max(0.0, min(1.0, float(confidence))), 3),
    }
    out_path = candidate_dir / f"{ident}.json"
    write_json_dict(out_path, payload)
    payload["_path"] = str(out_path)
    return payload


def learning_candidate_counts(
    project_root: Path,
    *,
    work_item_id: str,
    agent_id: str = "",
    loop_attempt: int | None = None,
) -> dict[str, int]:
    memory = iter_staged_records(
        memory_proposals_dir(project_root),
        schema=MEMORY_PROPOSAL_SCHEMA,
        work_item_id=work_item_id,
        status="proposed",
        agent_id=agent_id,
        loop_attempt=loop_attempt,
    )
    lessons = iter_staged_records(
        lesson_candidates_dir(project_root),
        schema=LESSON_CANDIDATE_SCHEMA,
        work_item_id=work_item_id,
        status="proposed",
        agent_id=agent_id,
        loop_attempt=loop_attempt,
    )
    return {
        "memory_candidate_count": len(memory),
        "lesson_candidate_count": len(lessons),
    }


def build_learning_capture_prompt(
    project_root: Path,
    *,
    work_item_id: str,
    source_agent: str,
    agent_id: str = "",
    loop_attempt: int = 0,
) -> str:
    memory_script = SCRIPT_DIR / "memory_proposal_capture.py"
    lesson_script = SCRIPT_DIR / "lessons_candidate_capture.py"
    loop_bits = f" --loop-attempt {int(loop_attempt)}" if int(loop_attempt or 0) > 0 else ""
    agent_bits = f" --agent-id {agent_id}" if str(agent_id or "").strip() else ""
    return (
        "Memory and lessons policy:\n"
        f"- You may read durable memory in {global_memory_path()} and the project memory file for this project when present.\n"
        "- Do not edit durable memory files directly.\n"
        "- Only propose durable memory when the finding is stable: workflow rule, durable decision, repeated pitfall, or enduring follow-up.\n"
        "- Only propose lessons when the finding is reusable and non-trivial.\n"
        "- If you have a durable memory candidate, write it with a staged proposal command like:\n"
        f"  python3 {memory_script} --project {project_root} --work-item-id {work_item_id} --source-agent {source_agent}{agent_bits} --scope project --kind workflow --statement \"<durable rule>\" --evidence \"<brief evidence>\" --promote-reason \"<why this should persist>\"{loop_bits}\n"
        "- If you have a reusable lesson, write it with a staged lesson candidate command like:\n"
        f"  python3 {lesson_script} --project {project_root} --work-item-id {work_item_id} --source-agent {source_agent}{agent_bits} --tags verification --linked {work_item_id} --context \"<what happened>\" --worked \"<what worked>\" --recommendation \"<what to do next time>\"{loop_bits}\n"
        "- If there is no durable memory or lesson candidate, do not create one."
    )


def memory_group_fingerprint(record: dict[str, Any]) -> str:
    return "|".join(
        [
            normalize_text(record.get("scope")),
            normalize_text(record.get("kind")),
            normalize_text(record.get("statement")),
        ]
    )


def lesson_group_fingerprint(record: dict[str, Any]) -> str:
    anchor = normalize_text(record.get("recommendation")) or normalize_text(record.get("worked")) or normalize_text(record.get("context"))
    return "|".join(
        [
            normalize_text(record.get("work_item_id")),
            anchor,
            normalize_text(record.get("failed")),
        ]
    )


def _replace_last_updated(text: str) -> str:
    stamp = today_iso_date()
    lines = text.splitlines()
    if lines and lines[0].startswith("# "):
        if len(lines) >= 2 and lines[1].startswith("Last updated:"):
            lines[1] = f"Last updated: {stamp}"
            return "\n".join(lines).rstrip() + "\n"
        insert = [lines[0], "", f"Last updated: {stamp}", ""]
        rest = lines[1:]
        return "\n".join(insert + rest).rstrip() + "\n"
    return f"Last updated: {stamp}\n\n{text.rstrip()}\n"


def _bootstrap_memory_text(title: str) -> str:
    return f"# {title} Memory\n\nLast updated: {today_iso_date()}\n"


def _append_section_blocks(text: str, heading: str, blocks: list[str]) -> str:
    if not blocks:
        return text

    marker = f"## {heading}"
    normalized = text.rstrip()
    if marker not in normalized:
        chunk = "\n\n".join(blocks)
        return normalized + f"\n\n{marker}\n\n{chunk}\n"

    pre, rest = normalized.split(marker, 1)
    rest_lines = rest.splitlines()
    insert_at = len(rest_lines)
    for idx, line in enumerate(rest_lines[1:], start=1):
        if line.startswith("## "):
            insert_at = idx
            break
    section_lines = rest_lines[:insert_at]
    if section_lines and section_lines[-1].strip():
        section_lines.append("")
    section_lines.extend(blocks)
    new_rest = section_lines + rest_lines[insert_at:]
    return (pre + marker + "\n" + "\n".join(new_rest)).rstrip() + "\n"


def memory_entry_block(record: dict[str, Any]) -> str:
    details: list[str] = []
    evidence = unique_values(record.get("evidence") or [])
    if evidence:
        details.append(f"Evidence: {'; '.join(evidence[:3])}")
    promote_reason = str(record.get("promote_reason") or "").strip()
    if promote_reason:
        details.append(f"Why keep it: {promote_reason}")
    sources = unique_values(record.get("source_agents") or [])
    if sources:
        details.append(f"Sources: {', '.join(sources[:3])}")

    lines = [f"- {str(record.get('statement') or '').strip()}"]
    lines.extend(f"  {item}" for item in details)
    return "\n".join(lines)


def memory_contains_statement(text: str, statement: str) -> bool:
    needle = normalize_text(statement)
    if not needle:
        return False
    for line in text.splitlines():
        if line.lstrip().startswith("- ") and needle == normalize_text(line[2:]):
            return True
    return needle in normalize_text(text)


def append_memory_entries(memory_path: Path, *, project_root: Path, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ensure_dir(memory_path.parent)
    text = memory_path.read_text(encoding="utf-8", errors="ignore") if memory_path.exists() else _bootstrap_memory_text(project_title(project_root))
    text = _replace_last_updated(text)

    grouped: dict[str, list[str]] = {}
    promoted: list[dict[str, Any]] = []
    for entry in entries:
        statement = str(entry.get("statement") or "").strip()
        if not statement or memory_contains_statement(text, statement):
            continue
        kind = str(entry.get("kind") or "workflow").strip().lower()
        heading = MEMORY_SECTION_TITLES.get(kind, "Workflow")
        grouped.setdefault(heading, []).append(memory_entry_block(entry))
        promoted.append(entry)

    for heading, blocks in grouped.items():
        text = _append_section_blocks(text, heading, blocks)

    memory_path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return promoted
