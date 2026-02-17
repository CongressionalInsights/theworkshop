#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from plan_sync import sync_project_plans
from twlib import (
    list_job_dirs,
    list_workstream_dirs,
    normalize_str_list,
    now_iso,
    read_md,
    resolve_project_root,
    write_md,
)


DEFAULT_TRUTH_CHECKS = [
    "exists_nonempty",
    "freshness",
    "required_command_logged",
    "verification_consistency",
]


def _file_exists_nonempty(path: Path) -> bool:
    try:
        return path.exists() and path.is_file() and path.stat().st_size > 0
    except Exception:
        return False


def _load_exec_entries(project_root: Path, wi: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    log_path = project_root / "logs" / "execution.jsonl"
    if not log_path.exists():
        return entries
    for raw in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        if str(obj.get("work_item_id") or "").strip() == wi:
            entries.append(obj)
    return entries


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _file_sig(path: Path, rel: str) -> dict[str, Any]:
    st = path.stat()
    return {
        "path": rel,
        "size": int(st.st_size),
        "mtime": int(st.st_mtime),
        "sha256": _sha256_file(path),
    }


def _read_input_snapshot(project_root: Path, job_dir: Path, frontmatter: dict[str, Any]) -> tuple[bool, str]:
    rel = str(frontmatter.get("truth_input_snapshot") or "artifacts/input-snapshot.json").strip()
    snap_path = job_dir / rel
    if not snap_path.exists():
        return False, f"missing input snapshot: {rel}"
    try:
        payload = json.loads(snap_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"input snapshot unreadable: {rel}: {exc}"

    entries: list[dict[str, Any]] = []
    inputs = payload.get("inputs")
    if isinstance(inputs, list):
        entries.extend([item for item in inputs if isinstance(item, dict)])
    dependencies = payload.get("dependencies")
    if isinstance(dependencies, list):
        for dep in dependencies:
            if not isinstance(dep, dict):
                continue
            outputs = dep.get("outputs")
            if not isinstance(outputs, list):
                continue
            for out in outputs:
                if isinstance(out, dict):
                    entries.append(out)

    if not entries:
        return False, "input snapshot has no comparable entries"

    for item in entries:
        rel_path = str(item.get("path") or "").strip()
        out_path = str(item.get("output_path") or "").strip()
        dep_path = None
        if out_path:
            dep_path = (project_root / out_path).resolve()
        elif rel_path:
            dep_path = (job_dir / rel_path).resolve()
        if dep_path is None:
            return False, "input snapshot item missing path"
        size = item.get("size")
        if size is None:
            size = item.get("size_bytes")
        mtime = item.get("mtime")
        sha = str(item.get("sha256") or "").strip()
        if not dep_path.exists():
            path_label = out_path or rel_path
            return False, f"snapshot input missing now: {path_label}"
        try:
            st = dep_path.stat()
        except Exception:
            path_label = out_path or rel_path
            return False, f"snapshot input unreadable now: {path_label}"
        if size is not None and int(st.st_size) != int(size):
            path_label = out_path or rel_path
            return False, f"snapshot stale (size changed): {path_label}"
        if mtime is not None and int(st.st_mtime) != int(float(mtime)):
            path_label = out_path or rel_path
            return False, f"snapshot stale (mtime changed): {path_label}"
        # Hash check is the strongest signal.
        if sha:
            try:
                cur_sha = _sha256_file(dep_path)
            except Exception:
                path_label = out_path or rel_path
                return False, f"snapshot stale (hash unreadable): {path_label}"
            if cur_sha != sha:
                path_label = out_path or rel_path
                return False, f"snapshot stale (hash changed): {path_label}"
    return True, "input snapshot matches dependency outputs"


def _looks_verification_contradictory(text: str) -> tuple[bool, str]:
    t = (text or "").strip()
    if not t:
        return True, "verification file is empty"

    patterns = [
        (r"cannot\s+be\s+marked\s+\"?done\"?", "contains phrase indicating work is not done"),
        (r"\bblocking\s+issue\b", "contains 'blocking issue'"),
        (r"^\s*-\s*\[!\]", "contains explicit blocker checkbox"),
        (r"\bstill\s+blocked\b", "contains 'still blocked'"),
        (r"\bnext\s+action\b", "contains unresolved next action"),
    ]
    for pat, reason in patterns:
        if re.search(pat, t, flags=re.IGNORECASE | re.MULTILINE):
            return True, reason
    return False, "verification narrative is consistent"


def _parse_pdf_big_images(pdf_path: Path) -> tuple[bool, int, str]:
    try:
        proc = subprocess.run(
            ["pdfimages", "-list", str(pdf_path)],
            text=True,
            capture_output=True,
            check=False,
        )
    except Exception as exc:
        return False, 0, f"pdfimages failed: {exc}"
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        return False, 0, f"pdfimages non-zero exit: {stderr}"

    big = 0
    for ln in (proc.stdout or "").splitlines():
        cols = ln.split()
        if len(cols) < 5:
            continue
        if not cols[0].isdigit():
            continue
        try:
            width = int(cols[3])
            height = int(cols[4])
        except Exception:
            continue
        if width >= 400 or height >= 400:
            big += 1
    return True, big, "ok"


def _image_size(path: Path) -> tuple[int, int] | None:
    # Fast PNG parser fallback.
    try:
        with path.open("rb") as fh:
            head = fh.read(32)
        if len(head) >= 24 and head[:8] == b"\x89PNG\r\n\x1a\n":
            w = int.from_bytes(head[16:20], "big")
            h = int.from_bytes(head[20:24], "big")
            return w, h
    except Exception:
        pass

    # Try sips on macOS.
    try:
        proc = subprocess.run(
            ["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)],
            text=True,
            capture_output=True,
            check=False,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    width = None
    height = None
    for ln in (proc.stdout or "").splitlines():
        if "pixelWidth:" in ln:
            try:
                width = int(ln.split(":", 1)[1].strip())
            except Exception:
                width = None
        if "pixelHeight:" in ln:
            try:
                height = int(ln.split(":", 1)[1].strip())
            except Exception:
                height = None
    if width and height:
        return width, height
    return None


def evaluate_job_truth(project_root: Path, job_dir: Path) -> dict[str, Any]:
    plan = read_md(job_dir / "plan.md")
    fm = plan.frontmatter
    wi = str(fm.get("work_item_id") or "").strip()
    status = str(fm.get("status") or "planned").strip()

    truth_mode = str(fm.get("truth_mode") or "strict").strip().lower()
    checks = normalize_str_list(fm.get("truth_checks"))
    if not checks:
        checks = list(DEFAULT_TRUTH_CHECKS)

    outputs = normalize_str_list(fm.get("outputs"))
    evid = normalize_str_list(fm.get("verification_evidence"))

    # Type-aware deterministic checks.
    has_pdf = any(str(o).lower().endswith(".pdf") for o in outputs)
    has_image = any(str(o).lower().endswith((".png", ".jpg", ".jpeg", ".webp")) for o in outputs)
    if has_pdf and "pdf_embeds_images" not in checks:
        checks.append("pdf_embeds_images")
    if has_image and "image_dimensions" not in checks:
        checks.append("image_dimensions")

    result_checks: list[dict[str, Any]] = []
    failures: list[str] = []

    if truth_mode == "off":
        return {
            "work_item_id": wi,
            "status": status,
            "truth_mode": truth_mode,
            "truth_status": "pass",
            "checks": [{"name": "truth_mode", "pass": True, "detail": "truth_mode=off"}],
            "failures": [],
        }

    def add_check(name: str, ok: bool, detail: str, extra: dict[str, Any] | None = None) -> None:
        item: dict[str, Any] = {"name": name, "pass": bool(ok), "detail": detail}
        if extra:
            item.update(extra)
        result_checks.append(item)
        if not ok:
            failures.append(f"{name}: {detail}")

    if "exists_nonempty" in checks:
        missing = []
        for rel in outputs:
            p = job_dir / rel
            if not _file_exists_nonempty(p):
                missing.append(rel)
        for rel in evid:
            p = job_dir / rel
            if not _file_exists_nonempty(p):
                missing.append(rel)
        if missing:
            add_check("exists_nonempty", False, "missing/empty files: " + ", ".join(missing[:8]), {"missing": missing})
        else:
            add_check("exists_nonempty", True, "all declared outputs and evidence are non-empty")

    if "freshness" in checks:
        out_paths = [job_dir / rel for rel in outputs if _file_exists_nonempty(job_dir / rel)]
        ev_paths = [job_dir / rel for rel in evid if _file_exists_nonempty(job_dir / rel)]
        if out_paths and ev_paths:
            out_latest = max(int(p.stat().st_mtime) for p in out_paths)
            # Prefer verification.md freshness signal when present.
            verification_path = None
            for rel in evid:
                if rel.endswith("verification.md"):
                    verification_path = job_dir / rel
                    break
            if verification_path and _file_exists_nonempty(verification_path):
                ev_ref = int(verification_path.stat().st_mtime)
            else:
                ev_ref = max(int(p.stat().st_mtime) for p in ev_paths)
            if ev_ref < out_latest:
                add_check("freshness", False, "verification evidence is older than outputs")
            else:
                add_check("freshness", True, "verification evidence is at least as fresh as outputs")
        else:
            add_check("freshness", True, "skipped freshness check (outputs/evidence unavailable)")

        deps = normalize_str_list(fm.get("depends_on"))
        if deps:
            ok, detail = _read_input_snapshot(project_root, job_dir, fm)
            add_check("freshness_inputs", ok, detail)

    if "required_command_logged" in checks:
        required = normalize_str_list(fm.get("truth_required_commands"))
        if not required:
            add_check("required_command_logged", True, "no required command patterns configured")
        else:
            entries = _load_exec_entries(project_root, wi)
            hay = "\n".join(
                [
                    f"{e.get('label','')}\n{e.get('command','')}"
                    for e in entries
                ]
            ).lower()
            missing_patterns = [pat for pat in required if pat.lower() not in hay]
            if missing_patterns:
                add_check(
                    "required_command_logged",
                    False,
                    "missing command patterns in logs: " + ", ".join(missing_patterns[:6]),
                    {"missing_patterns": missing_patterns},
                )
            else:
                add_check("required_command_logged", True, "all required command patterns found in execution logs")

    if "verification_consistency" in checks:
        ver_rel = ""
        for rel in evid:
            if rel.endswith("verification.md"):
                ver_rel = rel
                break
        if ver_rel:
            ver_path = job_dir / ver_rel
            if _file_exists_nonempty(ver_path):
                text = ver_path.read_text(encoding="utf-8", errors="ignore")
                bad, reason = _looks_verification_contradictory(text)
                add_check("verification_consistency", not bad, reason)
            else:
                add_check("verification_consistency", False, f"missing verification file: {ver_rel}")
        else:
            add_check("verification_consistency", False, "no verification.md declared in verification_evidence")

    if "pdf_embeds_images" in checks:
        pdfs = [job_dir / rel for rel in outputs if str(rel).lower().endswith(".pdf") and _file_exists_nonempty(job_dir / rel)]
        image_count = sum(1 for rel in outputs if str(rel).lower().endswith((".png", ".jpg", ".jpeg", ".webp")))
        expected_big = max(1, image_count) if image_count else 1
        if not pdfs:
            add_check("pdf_embeds_images", True, "no pdf outputs found; check skipped")
        else:
            ok_all = True
            details: list[str] = []
            for pdf in pdfs:
                ok_cmd, big, detail = _parse_pdf_big_images(pdf)
                if not ok_cmd:
                    ok_all = False
                    details.append(f"{pdf.name}: {detail}")
                    continue
                if big < expected_big:
                    ok_all = False
                    details.append(f"{pdf.name}: big_images={big} expected>={expected_big}")
                else:
                    details.append(f"{pdf.name}: big_images={big} expected>={expected_big}")
            add_check("pdf_embeds_images", ok_all, "; ".join(details))

    if "image_dimensions" in checks:
        images = [job_dir / rel for rel in outputs if str(rel).lower().endswith((".png", ".jpg", ".jpeg", ".webp")) and _file_exists_nonempty(job_dir / rel)]
        if not images:
            add_check("image_dimensions", True, "no image outputs found; check skipped")
        else:
            bad: list[str] = []
            dims: list[str] = []
            for img in images:
                size = _image_size(img)
                if not size:
                    bad.append(f"{img.name}: unreadable dimensions")
                    continue
                w, h = size
                dims.append(f"{img.name}={w}x{h}")
                if w < 256 or h < 256:
                    bad.append(f"{img.name}: too small ({w}x{h})")
            if bad:
                add_check("image_dimensions", False, "; ".join(bad), {"dimensions": dims})
            else:
                add_check("image_dimensions", True, "; ".join(dims), {"dimensions": dims})

    truth_status = "pass" if not failures else "fail"
    return {
        "work_item_id": wi,
        "status": status,
        "truth_mode": truth_mode,
        "truth_status": truth_status,
        "checks": result_checks,
        "failures": failures,
    }


def _render_job_md(payload: dict[str, Any], ts: str) -> str:
    lines = [
        "# Truth Report",
        "",
        f"- Generated: {ts}",
        f"- Work Item: {payload.get('work_item_id','')}",
        f"- Status: {payload.get('status','')}",
        f"- Truth Status: {payload.get('truth_status','')}",
        "",
        "## Checks",
        "",
        "| Check | Result | Detail |",
        "| --- | --- | --- |",
    ]
    for item in payload.get("checks", []):
        name = str(item.get("name") or "")
        result = "PASS" if bool(item.get("pass")) else "FAIL"
        detail = str(item.get("detail") or "").replace("|", "\\|")
        lines.append(f"| {name} | {result} | {detail} |")
    if not payload.get("checks"):
        lines.append("| (none) |  |  |")

    failures = payload.get("failures") or []
    lines.append("")
    lines.append("## Failures")
    lines.append("")
    if failures:
        for item in failures:
            lines.append(f"- {item}")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def _find_job_dir(project_root: Path, wi: str) -> Path:
    matches = list(project_root.glob(f"workstreams/WS-*/jobs/{wi}-*"))
    if len(matches) != 1:
        raise SystemExit(f"Expected exactly 1 job dir for {wi}; got {len(matches)}")
    return matches[0]


def _target_jobs(project_root: Path, wi: str | None) -> list[Path]:
    if wi:
        return [_find_job_dir(project_root, wi)]
    out: list[Path] = []
    for ws_dir in list_workstream_dirs(project_root):
        out.extend(list_job_dirs(ws_dir))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate artifact truth for TheWorkshop jobs.")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--work-item-id", help="Evaluate only one WI")
    parser.add_argument("--no-sync", action="store_true", help="Do not run plan_sync after writing truth metadata")
    parser.add_argument("--no-dashboard", action="store_true", help="Skip dashboard rebuild after truth eval")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    ts = now_iso()

    results: list[dict[str, Any]] = []
    for job_dir in _target_jobs(project_root, args.work_item_id):
        result = evaluate_job_truth(project_root, job_dir)
        result["generated_at"] = ts
        result["project"] = str(project_root)
        results.append(result)

        # Persist per-job truth artifacts.
        artifacts_dir = job_dir / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        (artifacts_dir / "truth-report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        (artifacts_dir / "truth-report.md").write_text(_render_job_md(result, ts), encoding="utf-8")

        # Update job frontmatter control-plane fields.
        plan_path = job_dir / "plan.md"
        doc = read_md(plan_path)
        doc.frontmatter.setdefault("truth_mode", "strict")
        doc.frontmatter.setdefault("truth_checks", list(DEFAULT_TRUTH_CHECKS))
        doc.frontmatter.setdefault("truth_required_commands", [])
        doc.frontmatter.setdefault("truth_input_snapshot", "artifacts/input-snapshot.json")
        doc.frontmatter["truth_last_status"] = str(result.get("truth_status") or "fail")
        doc.frontmatter["truth_last_checked_at"] = ts
        doc.frontmatter["truth_last_failures"] = list(result.get("failures") or [])
        doc.frontmatter["updated_at"] = ts
        write_md(plan_path, doc)

    outputs_dir = project_root / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "theworkshop.truth.v1",
        "generated_at": ts,
        "project": str(project_root),
        "jobs": results,
    }
    (outputs_dir / "truth-report.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    md_lines = ["# Truth Report", "", f"- Generated: {ts}", "", "| Work Item | Truth | Failures |", "| --- | --- | --- |"]
    for item in results:
        wi = str(item.get("work_item_id") or "")
        truth = str(item.get("truth_status") or "")
        failures = item.get("failures") or []
        fail_text = "; ".join(str(x) for x in failures[:3]).replace("|", "\\|") if failures else "none"
        md_lines.append(f"| {wi} | {truth} | {fail_text} |")
    if not results:
        md_lines.append("| (none) |  |  |")
    (outputs_dir / "truth-report.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    if not args.no_sync:
        sync_project_plans(project_root, ts=ts)

    if not args.no_dashboard:
        try:
            subprocess.run(
                ["python3", str(Path(__file__).resolve().parent / "dashboard_build.py"), "--project", str(project_root)],
                check=False,
                capture_output=True,
                text=True,
            )
        except Exception:
            pass

    print(str(outputs_dir / "truth-report.json"))


if __name__ == "__main__":
    main()
