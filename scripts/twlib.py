from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from math import ceil
from pathlib import Path
from typing import Any, Iterable

from twyaml import MarkdownDoc, YamlLiteError, join_frontmatter, split_frontmatter


STATUS_VALUES = {"planned", "in_progress", "blocked", "done", "cancelled"}
STAKE_VALUES = {"low", "normal", "high", "critical"}
TOKEN_RATES_PATH = Path("references") / "token-rates.json"
TOKEN_BASELINE_PATH = Path("logs") / "token-baseline.json"

def normalize_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        out = []
        for v in value:
            s = str(v).strip()
            if not s or s in {"[]", "{}"}:
                continue
            out.append(s)
        return out
    if isinstance(value, str):
        s = value.strip()
        if not s or s in {"[]", "{}"}:
            return []
        # Allow comma-separated fallback
        parts = [p.strip() for p in s.split(",")]
        return [p for p in parts if p and p not in {"[]", "{}"}]
    return []


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def today_yyyymmdd() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def today_iso_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def kebab(text: str) -> str:
    t = text.strip().lower()
    t = re.sub(r"[^a-z0-9]+", "-", t)
    t = re.sub(r"-{2,}", "-", t).strip("-")
    return t or "untitled"


def codex_home() -> Path:
    env = os.environ.get("CODEX_HOME")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".codex"


def skill_root() -> Path:
    # scripts/ is inside the repo; resolve from this file.
    return Path(__file__).resolve().parent.parent


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def read_md(path: Path) -> MarkdownDoc:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    return split_frontmatter(text)


def write_md(path: Path, doc: MarkdownDoc) -> None:
    path.write_text(join_frontmatter(doc), encoding="utf-8")


def set_frontmatter_field(doc: MarkdownDoc, key: str, value: Any) -> None:
    # Preserve insertion order: update in place.
    if key in doc.frontmatter:
        doc.frontmatter[key] = value
        return
    doc.frontmatter[key] = value


def require_frontmatter(doc: MarkdownDoc, keys: Iterable[str], ctx: str) -> list[str]:
    missing = [k for k in keys if k not in doc.frontmatter]
    return [f"{ctx}: missing frontmatter key {k!r}" for k in missing]


def parse_time(value: str) -> datetime | None:
    if not value:
        return None
    v = value.strip()
    try:
        if v.endswith("Z"):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return datetime.fromisoformat(v)
    except Exception:
        return None


def format_duration(seconds: float) -> str:
    s = int(seconds)
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    if h:
        return f"{h}h {m}m {sec}s"
    if m:
        return f"{m}m {sec}s"
    return f"{sec}s"


def project_root_from(path: Path) -> Path | None:
    cur = path.resolve()
    for _ in range(50):
        plan = cur / "plan.md"
        if plan.exists():
            try:
                doc = read_md(plan)
                if doc.frontmatter.get("kind") == "project":
                    return cur
            except Exception:
                pass
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def resolve_project_root(project: str | None) -> Path:
    if project:
        return Path(project).expanduser().resolve()
    found = project_root_from(Path.cwd())
    if not found:
        raise SystemExit("No --project provided and no project plan.md found in parent directories.")
    return found


def _extract_counter(id_text: str, prefix: str, date: str) -> int | None:
    m = re.match(rf"^{re.escape(prefix)}-{re.escape(date)}-(\d{{3}})$", id_text)
    if not m:
        return None
    return int(m.group(1))


def next_id(prefix: str, date: str, existing: Iterable[str]) -> str:
    max_n = 0
    for item in existing:
        n = _extract_counter(item, prefix, date)
        if n is not None:
            max_n = max(max_n, n)
    return f"{prefix}-{date}-{max_n+1:03d}"


def list_workstream_dirs(project_root: Path) -> list[Path]:
    ws_dir = project_root / "workstreams"
    if not ws_dir.exists():
        return []
    dirs = []
    for p in sorted(ws_dir.iterdir()):
        if p.is_dir() and p.name.startswith("WS-"):
            dirs.append(p)
    return dirs


def list_job_dirs(workstream_dir: Path) -> list[Path]:
    jobs_dir = workstream_dir / "jobs"
    if not jobs_dir.exists():
        return []
    dirs = []
    for p in sorted(jobs_dir.iterdir()):
        if p.is_dir() and p.name.startswith("WI-"):
            dirs.append(p)
    return dirs


@dataclass
class Workstream:
    id: str
    title: str
    status: str
    path: Path
    depends_on: list[str]


@dataclass
class Job:
    work_item_id: str
    title: str
    status: str
    path: Path
    depends_on: list[str]
    wave_id: str
    reward_target: int
    reward_last_score: int
    reward_last_next_action: str
    loop_enabled: bool
    loop_mode: str
    loop_max_iterations: int
    loop_target_promise: str
    loop_status: str
    loop_last_attempt: int
    loop_last_started_at: str
    loop_last_stopped_at: str
    loop_stop_reason: str


def load_workstream(workstream_dir: Path) -> Workstream:
    plan = workstream_dir / "plan.md"
    doc = read_md(plan)
    ws_id = str(doc.frontmatter.get("id", "")).strip()
    title = str(doc.frontmatter.get("title", "")).strip()
    status = str(doc.frontmatter.get("status", "planned")).strip()
    depends = normalize_str_list(doc.frontmatter.get("depends_on"))
    return Workstream(id=ws_id, title=title, status=status, path=workstream_dir, depends_on=depends)


def load_job(job_dir: Path) -> Job:
    plan = job_dir / "plan.md"
    doc = read_md(plan)
    wi = str(doc.frontmatter.get("work_item_id", "")).strip()
    title = str(doc.frontmatter.get("title", "")).strip()
    status = str(doc.frontmatter.get("status", "planned")).strip()
    depends = normalize_str_list(doc.frontmatter.get("depends_on"))
    wave_id = str(doc.frontmatter.get("wave_id", "") or "").strip()
    reward_target = int(doc.frontmatter.get("reward_target", 0) or 0)
    reward_last_score = int(doc.frontmatter.get("reward_last_score", 0) or 0)
    reward_last_next_action = str(doc.frontmatter.get("reward_last_next_action", "") or "")
    loop_enabled = bool(doc.frontmatter.get("loop_enabled", False))
    loop_mode = str(doc.frontmatter.get("loop_mode", "") or "")
    loop_max_iterations = int(doc.frontmatter.get("loop_max_iterations", 0) or 0)
    loop_target_promise = str(doc.frontmatter.get("loop_target_promise", "") or "")
    loop_status = str(doc.frontmatter.get("loop_status", "") or "")
    loop_last_attempt = int(doc.frontmatter.get("loop_last_attempt", 0) or 0)
    loop_last_started_at = str(doc.frontmatter.get("loop_last_started_at", "") or "")
    loop_last_stopped_at = str(doc.frontmatter.get("loop_last_stopped_at", "") or "")
    loop_stop_reason = str(doc.frontmatter.get("loop_stop_reason", "") or "")
    return Job(
        work_item_id=wi,
        title=title,
        status=status,
        path=job_dir,
        depends_on=depends,
        wave_id=wave_id,
        reward_target=reward_target,
        reward_last_score=reward_last_score,
        reward_last_next_action=reward_last_next_action,
        loop_enabled=loop_enabled,
        loop_mode=loop_mode,
        loop_max_iterations=loop_max_iterations,
        loop_target_promise=loop_target_promise,
        loop_status=loop_status,
        loop_last_attempt=loop_last_attempt,
        loop_last_started_at=loop_last_started_at,
        loop_last_stopped_at=loop_last_stopped_at,
        loop_stop_reason=loop_stop_reason,
    )


def scan_project(project_root: Path) -> tuple[MarkdownDoc, list[Workstream], list[Job]]:
    proj_doc = read_md(project_root / "plan.md")
    workstreams = [load_workstream(p) for p in list_workstream_dirs(project_root)]
    jobs: list[Job] = []
    for ws in workstreams:
        for job_dir in list_job_dirs(ws.path):
            jobs.append(load_job(job_dir))
    return proj_doc, workstreams, jobs


def has_marker_block(text: str, start: str, end: str) -> bool:
    return start in text and end in text and text.index(start) < text.index(end)


def replace_marker_block(text: str, start: str, end: str, new_block: str) -> str:
    if not has_marker_block(text, start, end):
        # Append at end (best effort)
        if not text.endswith("\n"):
            text += "\n"
        return text + "\n" + start + "\n" + new_block.rstrip("\n") + "\n" + end + "\n"
    pre, rest = text.split(start, 1)
    _, post = rest.split(end, 1)
    if not pre.endswith("\n"):
        pre += "\n"
    return pre + start + "\n" + new_block.rstrip("\n") + "\n" + end + "\n" + post.lstrip("\n")


def render_project_workstreams_table(workstreams: list[Workstream]) -> str:
    lines = []
    lines.append("| Workstream | Status | Title | Depends On |")
    lines.append("| --- | --- | --- | --- |")
    for ws in workstreams:
        deps = ", ".join(ws.depends_on) if ws.depends_on else ""
        lines.append(f"| {ws.id} | {ws.status} | {ws.title} | {deps} |")
    if len(lines) == 2:
        lines.append("| (none) |  |  |  |")
    return "\n".join(lines)


def render_workstream_jobs_table(jobs: list[Job]) -> str:
    lines = []
    lines.append("| Work Item | Status | Title | Wave | Depends On | Reward | Next Action |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for j in jobs:
        deps = ", ".join(j.depends_on) if j.depends_on else ""
        reward = f"{j.reward_last_score}/{j.reward_target}" if j.reward_target else str(j.reward_last_score)
        next_action = j.reward_last_next_action.replace("\n", " ").strip()
        lines.append(f"| {j.work_item_id} | {j.status} | {j.title} | {j.wave_id} | {deps} | {reward} | {next_action} |")
    if len(lines) == 2:
        lines.append("| (none) |  |  |  |  |  |  |")
    return "\n".join(lines)


def write_workstreams_index(project_root: Path, workstreams: list[Workstream]) -> None:
    ws_index = project_root / "workstreams" / "index.md"
    ensure_dir(ws_index.parent)
    lines = []
    lines.append("# Workstreams")
    lines.append("")
    for ws in workstreams:
        rel = ws.path.relative_to(project_root)
        lines.append(f"- `{ws.id}` {ws.title} ({ws.status}) -> `{rel}/plan.md`")
    if not workstreams:
        lines.append("- (none)")
    ws_index.write_text("\n".join(lines) + "\n", encoding="utf-8")


def estimate_token_proxy(project_root: Path) -> tuple[int, int]:
    """
    Always-available estimate: sum of UTF-8 text characters across the “control plane”
    (plans/prompts/notes/outputs), then tokens ~= chars/4.
    """
    include_globs = [
        "plan.md",
        "workstreams/**/plan.md",
        "workstreams/**/prompt.md",
        "workstreams/**/notes/**/*.md",
        "workstreams/**/outputs/**/*.md",
        "notes/**/*.md",
        "outputs/**/*.md",
    ]
    total_chars = 0
    for pat in include_globs:
        for p in project_root.glob(pat):
            if not p.is_file():
                continue
            try:
                txt = p.read_text(encoding="utf-8", errors="ignore")
                total_chars += len(txt)
            except Exception:
                continue
    tokens = int(ceil(total_chars / 4.0))
    return tokens, total_chars


def _session_id() -> str:
    for k in ("THEWORKSHOP_SESSION_ID", "CODEX_THREAD_ID", "TERM_SESSION_ID", "ITERM_SESSION_ID"):
        v = str(os.environ.get(k) or "").strip()
        if v:
            return v
    return ""


def _normalize_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if value == 1:
            return True
        if value == 0:
            return False
    text = str(value).strip().lower()
    if text in {"true", "yes", "y", "1"}:
        return True
    if text in {"false", "no", "n", "0"}:
        return False
    return None


def _sanitize_json_like(value: Any, *, depth: int = 0) -> Any:
    if depth > 4:
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            key = str(k)[:120]
            out[key] = _sanitize_json_like(v, depth=depth + 1)
        return out
    if isinstance(value, list):
        return [_sanitize_json_like(v, depth=depth + 1) for v in value[:100]]
    return str(value)


def codex_session_token_snapshot(provider: str = "codex") -> dict[str, Any] | None:
    session_id = _session_id()
    if not session_id:
        return None

    sessions_root = codex_home() / "sessions"
    if not sessions_root.exists():
        return None

    matches: list[Path] = []
    try:
        for p in sessions_root.rglob("rollout-*.jsonl"):
            if session_id in p.name:
                matches.append(p)
    except Exception:
        return None
    if not matches:
        return None

    def _mtime(path: Path) -> float:
        try:
            return float(path.stat().st_mtime)
        except Exception:
            return 0.0

    target = sorted(matches, key=_mtime, reverse=True)[0]
    latest_total: dict[str, Any] | None = None
    latest_last: dict[str, Any] | None = None
    latest_context: Any = None
    latest_ts = ""
    latest_model = ""
    latest_rate_limit_id = ""
    latest_rate_limit_name = ""
    latest_rate_plan_type = ""
    latest_rate_credits_has_credits: bool | None = None
    latest_rate_credits_unlimited: bool | None = None
    latest_rate_limits_raw: dict[str, Any] = {}
    tracked_model = ""

    try:
        for raw in target.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not raw.strip():
                continue
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            obj_type = str(obj.get("type") or "")
            payload = obj.get("payload")
            if obj_type == "turn_context" and isinstance(payload, dict):
                tracked_model = str(payload.get("model") or "").strip() or tracked_model
                continue
            if obj_type != "event_msg" or not isinstance(payload, dict):
                continue
            if str(payload.get("type") or "") != "token_count":
                continue
            info = payload.get("info")
            if not isinstance(info, dict):
                continue
            total = info.get("total_token_usage")
            if not isinstance(total, dict):
                continue
            if total.get("total_tokens") is None:
                continue
            latest_total = total
            last = info.get("last_token_usage")
            latest_last = last if isinstance(last, dict) else {}
            latest_context = info.get("model_context_window")
            latest_ts = str(obj.get("timestamp") or "")
            latest_model = tracked_model
            rate_limits = payload.get("rate_limits")
            if isinstance(rate_limits, dict):
                latest_rate_limit_id = str(rate_limits.get("limit_id") or "").strip()
                latest_rate_limit_name = str(rate_limits.get("limit_name") or "").strip()
                latest_rate_plan_type = str(rate_limits.get("plan_type") or "").strip()
                credits = rate_limits.get("credits")
                if isinstance(credits, dict):
                    latest_rate_credits_has_credits = _normalize_bool(credits.get("has_credits"))
                    latest_rate_credits_unlimited = _normalize_bool(credits.get("unlimited"))
                latest_rate_limits_raw = _sanitize_json_like(rate_limits)
    except Exception:
        return None

    if latest_total is None:
        return None

    return {
        "provider": provider,
        "source": "codex_session_logs",
        "sessionTokens": latest_total.get("total_tokens"),
        "sessionCostUSD": None,
        "updatedAt": latest_ts,
        "tokenTimestamp": latest_ts,
        "totalTokenUsage": latest_total,
        "lastTokenUsage": latest_last or {},
        "modelContextWindow": latest_context,
        "sessionLogPath": str(target),
        "sessionId": session_id,
        "detectedModel": latest_model,
        "rateLimitId": latest_rate_limit_id,
        "rateLimitName": latest_rate_limit_name,
        "ratePlanType": latest_rate_plan_type,
        "rateCreditsHasCredits": latest_rate_credits_has_credits,
        "rateCreditsUnlimited": latest_rate_credits_unlimited,
        "rateLimitsRaw": latest_rate_limits_raw,
    }


def codexbar_cost_snapshot(provider: str = "codex") -> dict[str, Any] | None:
    if shutil.which("codexbar"):
        try:
            res = subprocess.run(
                ["codexbar", "cost", "--provider", provider, "--format", "json"],
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(res.stdout)
            # payload is array (one per provider) in CodexBar
            if isinstance(payload, list) and payload:
                for item in payload:
                    if item.get("provider") == provider:
                        if isinstance(item, dict):
                            item.setdefault("source", "codexbar")
                            return item
            if isinstance(payload, dict):
                payload.setdefault("source", "codexbar")
                return payload
        except Exception:
            pass

    # Fallback when codexbar is unavailable: use Codex Desktop session logs.
    return codex_session_token_snapshot(provider)


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except Exception:
        return None


def _safe_int(value: Any) -> int:
    try:
        return int(float(value))
    except Exception:
        return 0


def _normalize_usage_tokens(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    out = {
        "input_tokens": max(0, _safe_int(value.get("input_tokens"))),
        "cached_input_tokens": max(0, _safe_int(value.get("cached_input_tokens"))),
        "output_tokens": max(0, _safe_int(value.get("output_tokens"))),
        "reasoning_output_tokens": max(0, _safe_int(value.get("reasoning_output_tokens"))),
        "total_tokens": max(0, _safe_int(value.get("total_tokens"))),
    }
    if out["total_tokens"] <= 0:
        out["total_tokens"] = (
            out["input_tokens"] + out["output_tokens"] + out["reasoning_output_tokens"]
        )
    return out


def _deep_merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge_dict(out.get(key) or {}, value)
        else:
            out[key] = value
    return out


def load_token_rates(project_root: Path) -> dict[str, Any]:
    base_path = skill_root() / TOKEN_RATES_PATH
    warnings: list[str] = []

    rates: dict[str, Any] = {}
    if base_path.exists():
        try:
            payload = json.loads(base_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                rates = payload
            else:
                warnings.append(f"base rates is not a JSON object: {base_path}")
        except Exception as exc:
            warnings.append(f"could not parse base rates file {base_path}: {exc}")
    else:
        warnings.append(f"missing base rates file: {base_path}")

    if not rates:
        rates = {
            "schema": "theworkshop.tokenrates.v1",
            "version": 1,
            "updated_at": "",
            "default_currency": "USD",
            "fallback_model": "gpt-5.3-codex",
            "models": {
                "gpt-5.3-codex": {
                    "usd_per_1m": {
                        "input": 1.5,
                        "cached_input": 0.15,
                        "output": 8.0,
                        "reasoning_output": 8.0,
                    }
                }
            },
            "aliases": {},
        }

    override_path = project_root / "notes" / "token-rates.override.json"
    if override_path.exists():
        try:
            override = json.loads(override_path.read_text(encoding="utf-8"))
            if isinstance(override, dict):
                rates = _deep_merge_dict(rates, override)
            else:
                warnings.append(f"override file is not a JSON object: {override_path}")
        except Exception as exc:
            warnings.append(f"could not parse override rates file {override_path}: {exc}")

    if warnings:
        rates["_warnings"] = warnings
    return rates


def resolve_rate_model(snapshot: dict[str, Any], rates: dict[str, Any]) -> tuple[str, str, str]:
    models = rates.get("models")
    if not isinstance(models, dict) or not models:
        return "", "no model rates configured", "low"

    aliases_raw = rates.get("aliases")
    aliases: dict[str, str] = {}
    if isinstance(aliases_raw, dict):
        for key, value in aliases_raw.items():
            k = str(key or "").strip().lower()
            v = str(value or "").strip()
            if k and v:
                aliases[k] = v

    models_lower = {str(k).strip().lower(): str(k) for k in models.keys()}

    def _match_model(value: str) -> str:
        key = str(value or "").strip()
        if not key:
            return ""
        if key in models:
            return key
        return models_lower.get(key.lower(), "")

    candidates = [
        ("detectedModel", str(snapshot.get("detectedModel") or "").strip()),
        ("rateLimitName", str(snapshot.get("rateLimitName") or "").strip()),
        ("rateLimitId", str(snapshot.get("rateLimitId") or "").strip()),
        ("provider", str(snapshot.get("provider") or "").strip()),
    ]

    for field_name, value in candidates:
        if not value:
            continue
        matched = _match_model(value)
        if matched:
            return matched, f"matched {field_name}={value}", "medium"
        alias_target = aliases.get(value.lower())
        if alias_target:
            matched_alias = _match_model(alias_target)
            if matched_alias:
                return matched_alias, f"matched alias {field_name}={value} -> {matched_alias}", "medium"

    fallback = str(rates.get("fallback_model") or "").strip()
    if fallback:
        matched = _match_model(fallback)
        if matched:
            return matched, f"using fallback_model={matched}", "low"

    first_key = next(iter(models.keys()))
    return str(first_key), f"using first configured model={first_key}", "low"


def resolve_billing_mode(snapshot: dict[str, Any], exact_cost: float | None) -> tuple[str, str, str]:
    override = str(os.environ.get("THEWORKSHOP_BILLING_MODE") or "").strip().lower()
    valid = {"subscription_auth", "metered_api", "unknown"}
    if override:
        if override in valid:
            return override, f"env override THEWORKSHOP_BILLING_MODE={override}", "high"
        return "unknown", f"invalid THEWORKSHOP_BILLING_MODE={override!r}; expected one of {sorted(valid)}", "low"

    if exact_cost is not None:
        return "metered_api", "exact session cost available from codexbar", "high"

    source = str(snapshot.get("source") or "").strip().lower()
    rate_limit_id = str(snapshot.get("rateLimitId") or "").strip()
    rate_limit_name = str(snapshot.get("rateLimitName") or "").strip().lower()
    detected_model = str(snapshot.get("detectedModel") or "").strip().lower()

    if source == "codex_session_logs":
        rl_lower = rate_limit_id.lower()
        if rl_lower.startswith("codex"):
            confidence = "high" if rl_lower in {"codex", "codex_bengalfox"} or rl_lower.startswith("codex_") else "medium"
            return "subscription_auth", f"codex session logs rateLimitId={rate_limit_id}", confidence
        if "codex" in rate_limit_name or "codex" in detected_model:
            return "subscription_auth", "codex session logs indicate codex auth/session routing", "medium"

    return "unknown", "unable to determine billed mode from telemetry", "low"


def estimate_usd_from_tokens(total_usage: dict[str, Any], rates_for_model: dict[str, Any]) -> dict[str, Any]:
    usage = _normalize_usage_tokens(total_usage)
    rates_block = rates_for_model.get("usd_per_1m") if isinstance(rates_for_model, dict) else None
    if not isinstance(rates_block, dict):
        rates_block = rates_for_model if isinstance(rates_for_model, dict) else {}

    input_rate = _safe_float(rates_block.get("input")) or 0.0
    cached_rate = _safe_float(rates_block.get("cached_input")) or 0.0
    output_rate = _safe_float(rates_block.get("output")) or 0.0
    reasoning_rate = _safe_float(rates_block.get("reasoning_output"))
    if reasoning_rate is None:
        reasoning_rate = output_rate

    input_uncached = max(0, usage.get("input_tokens", 0) - usage.get("cached_input_tokens", 0))
    cached_input = usage.get("cached_input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    reasoning_tokens = usage.get("reasoning_output_tokens", 0)

    input_uncached_cost = (input_uncached * input_rate) / 1_000_000.0
    cached_cost = (cached_input * cached_rate) / 1_000_000.0
    output_cost = (output_tokens * output_rate) / 1_000_000.0
    reasoning_cost = (reasoning_tokens * reasoning_rate) / 1_000_000.0
    total_cost = input_uncached_cost + cached_cost + output_cost + reasoning_cost

    return {
        "total_cost_usd": round(total_cost, 6),
        "cost_breakdown": {
            "input_uncached": round(input_uncached_cost, 6),
            "cached_input": round(cached_cost, 6),
            "output": round(output_cost, 6),
            "reasoning_output": round(reasoning_cost, 6),
        },
        "token_breakdown": {
            "input_uncached_tokens": input_uncached,
            "cached_input_tokens": cached_input,
            "output_tokens": output_tokens,
            "reasoning_output_tokens": reasoning_tokens,
            "total_tokens": usage.get("total_tokens", 0),
        },
        "rates_used": {
            "input": input_rate,
            "cached_input": cached_rate,
            "output": output_rate,
            "reasoning_output": reasoning_rate,
        },
    }


def load_or_init_cost_baseline(project_root: Path, snapshot: dict[str, Any]) -> dict[str, Any]:
    baseline_path = project_root / TOKEN_BASELINE_PATH
    current_tokens = _normalize_usage_tokens(snapshot.get("totalTokenUsage"))
    session_id = str(snapshot.get("sessionId") or "").strip()
    ts = now_iso()

    state: dict[str, Any] = {
        "path": str(baseline_path),
        "available": False,
        "created": False,
        "reset": False,
        "reset_reason": "",
        "session_id": session_id,
        "baseline_tokens": {},
    }

    if not session_id or current_tokens.get("total_tokens", 0) <= 0:
        state["reset_reason"] = "no snapshot tokens or session id"
        return state

    existing: dict[str, Any] = {}
    if baseline_path.exists():
        try:
            payload = json.loads(baseline_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                existing = payload
        except Exception:
            existing = {}

    existing_session = str(existing.get("session_id") or "").strip()
    existing_tokens = _normalize_usage_tokens(existing.get("baseline_tokens"))
    is_valid_existing = existing_session and existing_tokens.get("total_tokens", 0) > 0

    should_create = not is_valid_existing
    should_reset = is_valid_existing and existing_session != session_id

    if should_create or should_reset:
        ensure_dir(baseline_path.parent)
        baseline_payload = {
            "schema": "theworkshop.tokenbaseline.v1",
            "created_at": ts if should_create else str(existing.get("created_at") or ts),
            "updated_at": ts,
            "session_id": session_id,
            "baseline_tokens": current_tokens,
            "model_hint": str(snapshot.get("detectedModel") or ""),
            "rate_limit_id": str(snapshot.get("rateLimitId") or ""),
            "rate_limit_name": str(snapshot.get("rateLimitName") or ""),
        }
        baseline_path.write_text(json.dumps(baseline_payload, indent=2) + "\n", encoding="utf-8")
        state["available"] = True
        state["created"] = should_create
        state["reset"] = should_reset
        if should_reset:
            state["reset_reason"] = f"session changed ({existing_session} -> {session_id})"
        state["baseline_tokens"] = current_tokens
        return state

    state["available"] = True
    state["baseline_tokens"] = existing_tokens
    return state


def estimate_project_delta_cost(snapshot: dict[str, Any], baseline: dict[str, Any], rates_for_model: dict[str, Any]) -> dict[str, Any]:
    current_tokens = _normalize_usage_tokens(snapshot.get("totalTokenUsage"))
    baseline_tokens = _normalize_usage_tokens((baseline or {}).get("baseline_tokens"))
    session_id = str(snapshot.get("sessionId") or "").strip()
    baseline_session = str((baseline or {}).get("session_id") or session_id).strip()

    out: dict[str, Any] = {
        "estimated_project_cost_usd": 0.0,
        "project_cost_baseline_tokens": baseline_tokens.get("total_tokens", 0),
        "project_cost_delta_tokens": 0,
        "project_cost_method": "none",
        "project_cost_reason": "",
        "project_token_delta_breakdown": {},
        "baseline_estimated_session_cost_usd": 0.0,
        "current_session_cost_usd": None,
    }

    if not session_id or not baseline_session or session_id != baseline_session:
        out["project_cost_reason"] = "baseline unavailable or session mismatch"
        return out

    if current_tokens.get("total_tokens", 0) <= 0 or baseline_tokens.get("total_tokens", 0) <= 0:
        out["project_cost_reason"] = "insufficient token usage for delta"
        return out

    delta_tokens = {
        "input_tokens": max(0, current_tokens.get("input_tokens", 0) - baseline_tokens.get("input_tokens", 0)),
        "cached_input_tokens": max(
            0, current_tokens.get("cached_input_tokens", 0) - baseline_tokens.get("cached_input_tokens", 0)
        ),
        "output_tokens": max(0, current_tokens.get("output_tokens", 0) - baseline_tokens.get("output_tokens", 0)),
        "reasoning_output_tokens": max(
            0, current_tokens.get("reasoning_output_tokens", 0) - baseline_tokens.get("reasoning_output_tokens", 0)
        ),
    }
    delta_tokens["total_tokens"] = max(0, current_tokens.get("total_tokens", 0) - baseline_tokens.get("total_tokens", 0))
    out["project_cost_delta_tokens"] = delta_tokens["total_tokens"]
    out["project_token_delta_breakdown"] = delta_tokens

    baseline_est = estimate_usd_from_tokens(baseline_tokens, rates_for_model)
    current_est = estimate_usd_from_tokens(current_tokens, rates_for_model)
    delta_est = estimate_usd_from_tokens(delta_tokens, rates_for_model)

    baseline_est_usd = float(baseline_est.get("total_cost_usd") or 0.0)
    current_est_usd = float(current_est.get("total_cost_usd") or 0.0)
    delta_est_usd = float(delta_est.get("total_cost_usd") or 0.0)
    out["baseline_estimated_session_cost_usd"] = round(baseline_est_usd, 6)

    exact_session_cost = _safe_float(snapshot.get("sessionCostUSD"))
    if exact_session_cost is not None:
        out["current_session_cost_usd"] = round(exact_session_cost, 6)
        out["estimated_project_cost_usd"] = round(max(0.0, exact_session_cost - baseline_est_usd), 6)
        out["project_cost_method"] = "exact_session_minus_estimated_baseline"
        out["project_cost_reason"] = "used exact session cost from codexbar"
        return out

    out["current_session_cost_usd"] = round(current_est_usd, 6)
    if current_est_usd > 0.0:
        out["estimated_project_cost_usd"] = round(max(0.0, current_est_usd - baseline_est_usd), 6)
        out["project_cost_method"] = "estimated_session_minus_estimated_baseline"
        out["project_cost_reason"] = "used estimated session cost from token rates"
        return out

    out["estimated_project_cost_usd"] = round(max(0.0, delta_est_usd), 6)
    out["project_cost_method"] = "delta_token_estimate"
    out["project_cost_reason"] = "used delta token estimate due to missing session estimate"
    return out


def allocate_project_cost_by_work_item(project_root: Path, project_cost_usd: float) -> dict[str, Any]:
    log_path = project_root / "logs" / "execution.jsonl"
    wi_weights: dict[str, float] = {}
    unattributed_weight = 0.0
    total_weight = 0.0

    if log_path.exists():
        for raw in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not raw.strip():
                continue
            try:
                obj = json.loads(raw)
            except Exception:
                continue
            duration = _safe_float(obj.get("duration_sec")) or 0.0
            weight = max(1.0, duration) + 0.5
            wi = str(obj.get("work_item_id") or "").strip()
            if wi:
                wi_weights[wi] = wi_weights.get(wi, 0.0) + weight
            else:
                unattributed_weight += weight
            total_weight += weight

    # Best-effort project delta token estimate from current snapshot vs baseline.
    project_delta_tokens = 0
    snapshot = codexbar_cost_snapshot("codex") or {}
    current_tokens = _normalize_usage_tokens(snapshot.get("totalTokenUsage"))
    baseline_path = project_root / TOKEN_BASELINE_PATH
    if baseline_path.exists() and current_tokens.get("total_tokens", 0) > 0:
        try:
            base_payload = json.loads(baseline_path.read_text(encoding="utf-8"))
            base_session = str(base_payload.get("session_id") or "").strip()
            snap_session = str(snapshot.get("sessionId") or "").strip()
            base_tokens = _normalize_usage_tokens(base_payload.get("baseline_tokens"))
            if base_session and snap_session and base_session == snap_session:
                project_delta_tokens = max(0, current_tokens.get("total_tokens", 0) - base_tokens.get("total_tokens", 0))
        except Exception:
            project_delta_tokens = 0

    if total_weight <= 0.0:
        return {
            "weight_formula": "max(1,duration_sec)+0.5",
            "project_delta_tokens": project_delta_tokens,
            "by_work_item": [],
            "unattributed_cost_usd": round(max(0.0, project_cost_usd), 6) if project_cost_usd > 0 else 0.0,
            "unattributed_tokens_allocated": project_delta_tokens,
        }

    rows: list[dict[str, Any]] = []
    for wi, weight in wi_weights.items():
        share = weight / total_weight
        rows.append(
            {
                "work_item_id": wi,
                "estimated_cost_usd": round(max(0.0, project_cost_usd) * share, 6),
                "weight_basis": round(weight, 3),
                "tokens_allocated": int(round(project_delta_tokens * share)),
            }
        )
    rows.sort(key=lambda item: (-float(item.get("estimated_cost_usd") or 0.0), str(item.get("work_item_id") or "")))

    unattributed_share = unattributed_weight / total_weight
    unattributed_cost = round(max(0.0, project_cost_usd) * unattributed_share, 6)
    unattributed_tokens = int(round(project_delta_tokens * unattributed_share))
    return {
        "weight_formula": "max(1,duration_sec)+0.5",
        "project_delta_tokens": project_delta_tokens,
        "by_work_item": rows,
        "unattributed_cost_usd": unattributed_cost,
        "unattributed_tokens_allocated": unattributed_tokens,
    }


def build_token_cost_payload(project_root: Path, provider: str = "codex") -> dict[str, Any]:
    estimated_tokens, estimated_chars = estimate_token_proxy(project_root)
    snapshot = codexbar_cost_snapshot(provider) or {}
    token_source = str(snapshot.get("source") or "none")
    total_usage = _normalize_usage_tokens(snapshot.get("totalTokenUsage"))
    last_usage = _normalize_usage_tokens(snapshot.get("lastTokenUsage"))

    rates = load_token_rates(project_root)
    model_key, resolution_reason, match_confidence = resolve_rate_model(snapshot, rates)
    model_rates = {}
    if model_key and isinstance(rates.get("models"), dict):
        model_rates = (rates.get("models") or {}).get(model_key) or {}

    session_est = estimate_usd_from_tokens(total_usage, model_rates) if total_usage.get("total_tokens", 0) > 0 else {}
    baseline = load_or_init_cost_baseline(project_root, snapshot)
    project_delta = estimate_project_delta_cost(snapshot, baseline, model_rates)
    snapshot_no_exact = dict(snapshot)
    snapshot_no_exact["sessionCostUSD"] = None
    project_delta_api_equivalent = estimate_project_delta_cost(snapshot_no_exact, baseline, model_rates)

    exact_cost = _safe_float(snapshot.get("sessionCostUSD"))
    if exact_cost is not None:
        cost_source = "codexbar_exact"
        cost_confidence = "high"
        estimated_session_cost = round(exact_cost, 6)
    elif session_est:
        cost_source = "estimated_from_rates"
        cost_confidence = match_confidence
        estimated_session_cost = float(session_est.get("total_cost_usd") or 0.0)
    else:
        cost_source = "none"
        cost_confidence = "none"
        estimated_session_cost = 0.0

    estimated_project_cost = float(project_delta.get("estimated_project_cost_usd") or 0.0)
    allocations = allocate_project_cost_by_work_item(project_root, estimated_project_cost)
    api_equivalent_session_cost = float(session_est.get("total_cost_usd") or 0.0) if isinstance(session_est, dict) else 0.0
    api_equivalent_project_cost = float(project_delta_api_equivalent.get("estimated_project_cost_usd") or 0.0)
    billing_mode, billing_reason, billing_confidence = resolve_billing_mode(snapshot, exact_cost)

    if billing_mode == "subscription_auth":
        billed_session_cost = 0.0
        billed_project_cost = 0.0
        display_cost_primary_label = "Billed cost (Codex auth/subscription)"
        display_cost_secondary_label = "API-equivalent estimate (non-billed)"
    elif billing_mode == "metered_api":
        billed_session_cost = round(float(exact_cost), 6) if exact_cost is not None else round(float(estimated_session_cost or 0.0), 6)
        if exact_cost is not None:
            billed_project_cost = round(float(project_delta.get("estimated_project_cost_usd") or 0.0), 6)
        else:
            billed_project_cost = round(float(api_equivalent_project_cost or 0.0), 6)
        display_cost_primary_label = "Billed cost (metered API)"
        display_cost_secondary_label = "API-equivalent estimate"
    else:
        billed_session_cost = round(float(estimated_session_cost or 0.0), 6)
        billed_project_cost = round(float(estimated_project_cost or 0.0), 6)
        display_cost_primary_label = "Estimated cost (billing mode unknown)"
        display_cost_secondary_label = "API-equivalent estimate (heuristic)"

    warnings = rates.get("_warnings") if isinstance(rates.get("_warnings"), list) else []
    rate_resolution = resolution_reason
    if warnings:
        rate_resolution = (rate_resolution + "; " if rate_resolution else "") + "; ".join(str(w) for w in warnings)

    return {
        "estimated_tokens": estimated_tokens,
        "estimated_chars": estimated_chars,
        "codexbar_available": bool(snapshot),
        "token_source": token_source,
        "codexbar_session_tokens": snapshot.get("sessionTokens"),
        "codexbar_session_cost_usd": snapshot.get("sessionCostUSD"),
        "codexbar_updated_at": snapshot.get("updatedAt"),
        "last_turn_tokens": (last_usage.get("total_tokens") if last_usage else None),
        "model_context_window": snapshot.get("modelContextWindow"),
        "session_log_path": snapshot.get("sessionLogPath"),
        "total_token_usage": total_usage if total_usage else {},
        "last_token_usage": last_usage if last_usage else {},
        "cost_source": cost_source,
        "cost_confidence": cost_confidence,
        "estimated_session_cost_usd": round(estimated_session_cost, 6) if estimated_session_cost else 0.0,
        "estimated_project_cost_usd": round(estimated_project_cost, 6),
        "billing_mode": billing_mode,
        "billing_confidence": billing_confidence,
        "billing_reason": billing_reason,
        "billed_session_cost_usd": round(float(billed_session_cost or 0.0), 6),
        "billed_project_cost_usd": round(float(billed_project_cost or 0.0), 6),
        "api_equivalent_session_cost_usd": round(float(api_equivalent_session_cost or 0.0), 6),
        "api_equivalent_project_cost_usd": round(float(api_equivalent_project_cost or 0.0), 6),
        "display_cost_primary_label": display_cost_primary_label,
        "display_cost_secondary_label": display_cost_secondary_label,
        "project_cost_baseline_tokens": int(project_delta.get("project_cost_baseline_tokens") or 0),
        "project_cost_delta_tokens": int(project_delta.get("project_cost_delta_tokens") or 0),
        "rate_model_key": model_key,
        "rate_resolution": rate_resolution,
        "cost_breakdown": (session_est.get("cost_breakdown") if isinstance(session_est, dict) else {}) or {},
        "by_work_item": allocations.get("by_work_item") if isinstance(allocations, dict) else [],
        "unattributed_cost_usd": float((allocations or {}).get("unattributed_cost_usd") or 0.0),
        "unattributed_tokens_allocated": int((allocations or {}).get("unattributed_tokens_allocated") or 0),
        "detected_model": str(snapshot.get("detectedModel") or ""),
        "rate_limit_id": str(snapshot.get("rateLimitId") or ""),
        "rate_limit_name": str(snapshot.get("rateLimitName") or ""),
        "project_cost_method": str(project_delta.get("project_cost_method") or ""),
    }


def run_gh(args: list[str], repo: str | None = None, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = ["gh"] + args
    if repo and "--repo" not in cmd:
        cmd.extend(["--repo", repo])
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def parse_git_remote_owner_repo(remote_url: str) -> str | None:
    url = remote_url.strip()
    # HTTPS: https://github.com/owner/repo.git
    m = re.match(r"^https?://github\\.com/([^/]+)/([^/]+?)(?:\\.git)?$", url)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    # SSH: git@github.com:owner/repo.git
    m = re.match(r"^git@github\\.com:([^/]+)/([^/]+?)(?:\\.git)?$", url)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    return None


def detect_github_repo(project_root: Path) -> str | None:
    try:
        res = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(project_root),
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    return parse_git_remote_owner_repo(res.stdout.strip())
