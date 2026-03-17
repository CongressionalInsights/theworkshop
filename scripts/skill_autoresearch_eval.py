#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from fnmatch import fnmatch
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PACK = ROOT / "autoresearch" / "benchmark-pack.fast.json"
RESULTS_HEADER = [
    "commit",
    "score",
    "passed",
    "failed",
    "scope_ok",
    "worktree_clean",
    "pack",
    "status",
    "description",
]


def run(
    cmd: list[str],
    *,
    cwd: Path,
    timeout_sec: int,
    env: dict[str, str] | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    merged = dict(os.environ)
    merged["THEWORKSHOP_NO_OPEN"] = "1"
    merged["THEWORKSHOP_NO_MONITOR"] = "1"
    merged["THEWORKSHOP_NO_KEYCHAIN"] = "1"
    if env:
        merged.update(env)
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        timeout=max(1, timeout_sec),
        env=merged,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            f"  cmd={' '.join(cmd)}\n"
            f"  exit={proc.returncode}\n"
            f"  stdout:\n{proc.stdout}\n"
            f"  stderr:\n{proc.stderr}\n"
        )
    return proc


def git(repo: Path, *args: str, timeout_sec: int = 30) -> str:
    proc = run(["git", *args], cwd=repo, timeout_sec=timeout_sec, check=True)
    return (proc.stdout or "").strip()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"Benchmark pack must be a JSON object: {path}")
    return payload


def _string(value: Any, default: str = "") -> str:
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return default
    if isinstance(value, (int, float, bool)):
        return str(value)
    return default


def _bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        token = value.strip().lower()
        if token in {"1", "true", "yes", "on"}:
            return True
        if token in {"0", "false", "no", "off"}:
            return False
    return default


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def changed_files(repo: Path, base_ref: str) -> list[str]:
    out = git(repo, "diff", "--name-only", "--relative", f"{base_ref}..HEAD")
    return [line.strip() for line in out.splitlines() if line.strip()]


def dirty_files(repo: Path) -> list[str]:
    proc = run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=repo,
        timeout_sec=30,
        check=True,
    )
    files: list[str] = []
    for raw in (proc.stdout or "").splitlines():
        line = raw.rstrip()
        if len(line) < 4:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        path = path.strip()
        if path:
            files.append(path)
    return files


def allowed(path: str, patterns: list[str]) -> bool:
    if not patterns:
        return True
    norm = path.strip().replace("\\", "/")
    return any(fnmatch(norm, pattern) for pattern in patterns)


def excerpt(text: str, limit: int = 800) -> str:
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[:limit] + "... (truncated)"


def summarize_stdout(stdout: str, stderr: str) -> dict[str, str]:
    return {
        "stdout_excerpt": excerpt(stdout),
        "stderr_excerpt": excerpt(stderr),
    }


def _scored_payload(text: str, bench_id: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except Exception as exc:
        raise SystemExit(f"Benchmark {bench_id!r} did not return valid JSON score payload: {exc}")
    if not isinstance(payload, dict):
        raise SystemExit(f"Benchmark {bench_id!r} score payload must be a JSON object")
    score = _float(payload.get("score"), -1.0)
    max_score = _float(payload.get("max_score"), -1.0)
    if score < 0 or max_score <= 0 or score > max_score:
        raise SystemExit(
            f"Benchmark {bench_id!r} returned invalid score payload: score={score} max_score={max_score}"
        )
    return payload


def run_benchmark(repo: Path, item: dict[str, Any], default_timeout: int) -> dict[str, Any]:
    bench_id = _string(item.get("id")) or "unnamed"
    command = item.get("command")
    if not isinstance(command, str) or not command.strip():
        raise SystemExit(f"Benchmark {bench_id!r} is missing string field 'command'")

    timeout_sec = _int(item.get("timeout_sec"), default_timeout)
    weight = _float(item.get("weight"), 1.0)
    mode = _string(item.get("mode")) or "binary"
    start = time.time()
    try:
        proc = run(["sh", "-lc", command], cwd=repo, timeout_sec=timeout_sec, check=False)
        timed_out = False
        exit_code = int(proc.returncode)
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = 124
        stdout = exc.stdout or ""
        stderr = (exc.stderr or "") + f"\nTimed out after {timeout_sec}s"
    duration_sec = round(time.time() - start, 3)
    passed = (not timed_out) and exit_code == 0
    result = {
        "id": bench_id,
        "label": _string(item.get("label")) or bench_id,
        "command": command,
        "mode": mode,
        "weight": weight,
        "timeout_sec": timeout_sec,
        "duration_sec": duration_sec,
        "exit_code": exit_code,
        "timed_out": timed_out,
    }
    result.update(summarize_stdout(stdout, stderr))
    if mode == "json_score" and not timed_out and exit_code == 0:
        payload = _scored_payload(stdout, bench_id)
        score = _float(payload.get("score"), 0.0)
        max_score = _float(payload.get("max_score"), 1.0)
        result["score"] = score
        result["max_score"] = max_score
        result["passed"] = score >= max_score
        result["fraction"] = score / max_score if max_score > 0 else 0.0
        checks = payload.get("checks")
        if isinstance(checks, list):
            result["checks"] = checks
        summary = _string(payload.get("summary"))
        if summary:
            result["summary"] = summary
    else:
        result["passed"] = passed
        result["score"] = 1.0 if passed else 0.0
        result["max_score"] = 1.0
        result["fraction"] = 1.0 if passed else 0.0
    return result


def compute_score(results: list[dict[str, Any]]) -> int:
    total = sum(max(0.0, float(item.get("weight") or 0.0)) for item in results)
    if total <= 0:
        return 100
    earned = sum(float(item.get("weight") or 0.0) * float(item.get("fraction") or 0.0) for item in results)
    return max(0, min(100, int(round((earned / total) * 100))))


def write_results_tsv(path: Path, payload: dict[str, Any], description: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("\t".join(RESULTS_HEADER) + "\n", encoding="utf-8")
    row = [
        _string(payload.get("commit")),
        str(int(payload.get("score") or 0)),
        str(int(payload.get("passed") or 0)),
        str(int(payload.get("failed") or 0)),
        "true" if _bool(payload.get("scope_ok")) else "false",
        "true" if _bool(payload.get("worktree_clean")) else "false",
        _string(payload.get("pack")),
        _string(payload.get("status")),
        description.replace("\t", " ").strip(),
    ]
    with path.open("a", encoding="utf-8") as fp:
        fp.write("\t".join(row) + "\n")


def markdown_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Skill Autoresearch Evaluation",
        "",
        f"- Pack: `{payload['pack']}`",
        f"- Commit: `{payload['commit']}`",
        f"- Diff base: `{payload['base_ref']}`",
        f"- Score: `{payload['score']}`",
        f"- Status: `{payload['status']}`",
        f"- Scope OK: `{payload['scope_ok']}`",
        f"- Worktree clean: `{payload['worktree_clean']}`",
        "",
    ]
    scope = payload.get("scope") if isinstance(payload.get("scope"), dict) else {}
    unauthorized = scope.get("unauthorized_files") if isinstance(scope.get("unauthorized_files"), list) else []
    dirty = scope.get("dirty_files") if isinstance(scope.get("dirty_files"), list) else []
    if unauthorized:
        lines.append("## Scope Violations")
        lines.append("")
        for path in unauthorized:
            lines.append(f"- `{path}`")
        lines.append("")
    if dirty:
        lines.append("## Dirty Worktree")
        lines.append("")
        for path in dirty:
            lines.append(f"- `{path}`")
        lines.append("")
        lines.extend(
        [
            "## Benchmarks",
            "",
            "| Benchmark | Status | Score | Weight | Duration (s) |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
    )
    for item in payload.get("benchmarks", []):
        fraction = float(item.get("fraction") or 0.0)
        if fraction >= 1.0:
            status = "pass"
        elif fraction <= 0.0:
            status = "fail"
        else:
            status = "partial"
        score_cell = f"{float(item.get('score') or 0.0):.1f}/{float(item.get('max_score') or 0.0):.1f}"
        lines.append(
            f"| {item.get('id')} | {status} | {score_cell} | {float(item.get('weight') or 0.0):.1f} | {float(item.get('duration_sec') or 0.0):.3f} |"
        )
        checks = item.get("checks") if isinstance(item.get("checks"), list) else []
        for check in checks:
            if not isinstance(check, dict):
                continue
            cid = _string(check.get("id")) or "check"
            cscore = _float(check.get("score"), 0.0)
            cmax = _float(check.get("max_score"), 0.0)
            message = _string(check.get("message"))
            marker = "ok" if cscore >= cmax and cmax > 0 else "gap"
            lines.append(f"  - `{cid}` `{cscore:.1f}/{cmax:.1f}` {marker} {message}".rstrip())
    if not payload.get("benchmarks"):
        lines.append("| (none) | skipped | 0.0/0.0 | 0.0 | 0.000 |")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate TheWorkshop skill-surface experiments with autoresearch-style benchmark packs.")
    parser.add_argument("--repo", default=str(ROOT), help="Repo root to evaluate.")
    parser.add_argument("--pack", default=str(DEFAULT_PACK), help="Path to benchmark pack JSON.")
    parser.add_argument("--diff-ref", default="HEAD~1", help="Git ref used to determine changed files for scope enforcement.")
    parser.add_argument("--format", choices=["json", "markdown"], default="markdown")
    parser.add_argument("--out", default="", help="Optional path to also write the formatted report.")
    parser.add_argument("--results-tsv", default="", help="Optional TSV file to append one summary row.")
    parser.add_argument("--description", default="", help="Free-text experiment description used when appending TSV rows.")
    args = parser.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    pack_path = Path(args.pack).expanduser().resolve()
    if not (repo / ".git").exists():
        raise SystemExit(f"Expected git repository at {repo}")
    if not pack_path.exists():
        raise SystemExit(f"Missing benchmark pack: {pack_path}")

    pack = load_json(pack_path)
    benchmarks = pack.get("benchmarks")
    if not isinstance(benchmarks, list) or not benchmarks:
        raise SystemExit(f"Benchmark pack must contain a non-empty 'benchmarks' array: {pack_path}")

    scope_policy = pack.get("scope_policy") if isinstance(pack.get("scope_policy"), dict) else {}
    allowed_globs = [
        _string(item)
        for item in pack.get("allowed_globs", [])
        if _string(item)
    ]
    reject_unauthorized = _bool(scope_policy.get("reject_unauthorized"), True)
    require_clean_worktree = _bool(scope_policy.get("require_clean_worktree"), True)
    default_timeout = _int(pack.get("default_timeout_sec"), 180)

    commit = git(repo, "rev-parse", "--short", "HEAD")
    changed = changed_files(repo, args.diff_ref)
    dirty = dirty_files(repo)
    unauthorized = [path for path in changed if not allowed(path, allowed_globs)]
    scope_ok = not unauthorized
    worktree_clean = len(dirty) == 0

    results: list[dict[str, Any]] = []
    failure_reasons: list[str] = []
    if reject_unauthorized and not scope_ok:
        failure_reasons.append("scope_violation")
    if require_clean_worktree and not worktree_clean:
        failure_reasons.append("dirty_worktree")

    if not failure_reasons:
        for item in benchmarks:
            results.append(run_benchmark(repo, item if isinstance(item, dict) else {}, default_timeout))

    score = 0 if failure_reasons else compute_score(results)
    passed = sum(1 for item in results if item.get("passed"))
    failed = len(results) - passed
    status = "pass" if not failure_reasons and failed == 0 else "fail"

    payload = {
        "schema": "theworkshop.skill-autoresearch-eval.v1",
        "pack": _string(pack.get("name")) or pack_path.stem,
        "pack_path": str(pack_path),
        "repo": str(repo),
        "commit": commit,
        "base_ref": args.diff_ref,
        "score": score,
        "status": status,
        "passed": passed,
        "failed": failed,
        "scope_ok": scope_ok,
        "worktree_clean": worktree_clean,
        "failure_reasons": failure_reasons,
        "scope": {
            "allowed_globs": allowed_globs,
            "changed_files": changed,
            "unauthorized_files": unauthorized,
            "dirty_files": dirty,
            "reject_unauthorized": reject_unauthorized,
            "require_clean_worktree": require_clean_worktree,
        },
        "benchmarks": results,
    }

    if args.results_tsv:
        write_results_tsv(Path(args.results_tsv).expanduser().resolve(), payload, args.description)

    rendered = json.dumps(payload, indent=2) + "\n" if args.format == "json" else markdown_report(payload)
    if args.out:
        out_path = Path(args.out).expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    raise SystemExit(0 if status == "pass" else 1)


if __name__ == "__main__":
    main()
