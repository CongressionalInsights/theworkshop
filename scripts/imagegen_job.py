#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from twlib import codex_home, normalize_str_list, now_iso, read_md, resolve_project_root


def find_job_dir(project_root: Path, wi: str) -> Path:
    matches = list(project_root.glob(f"workstreams/WS-*/jobs/{wi}-*"))
    if len(matches) != 1:
        raise SystemExit(f"Expected exactly 1 job dir for {wi}, got {len(matches)}: {matches}")
    return matches[0]


def file_exists_nonempty(path: Path) -> bool:
    try:
        return path.exists() and path.is_file() and path.stat().st_size > 0
    except Exception:
        return False


def keychain_service_exists(service: str) -> bool:
    proc = subprocess.run(
        ["security", "find-generic-password", "-s", service],
        text=True,
        capture_output=True,
    )
    return int(proc.returncode) == 0


def preferred_keychain_service() -> str | None:
    for service in ("OPENAI_KEY", "OPENAI_API_KEY"):
        if keychain_service_exists(service):
            return service
    return None


def parse_prompts_jsonl(path: Path, out_dir: Path) -> tuple[list[dict], list[Path]]:
    if not path.exists():
        raise SystemExit(f"Prompts file not found: {path}")
    jobs: list[dict] = []
    out_paths: list[Path] = []
    errors: list[str] = []

    for i, raw in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            errors.append(f"line {i}: not valid JSON")
            continue
        if not isinstance(obj, dict):
            errors.append(f"line {i}: expected object")
            continue
        prompt = str(obj.get("prompt") or "").strip()
        if not prompt:
            errors.append(f"line {i}: missing non-empty `prompt`")
            continue
        jobs.append(obj)
        out = str(obj.get("out") or "").strip()
        if out:
            out_path = Path(out).expanduser()
            if not out_path.is_absolute():
                out_path = out_dir / out_path
            out_paths.append(out_path.resolve())

    if errors:
        raise SystemExit("Invalid prompts JSONL:\n- " + "\n- ".join(errors))
    if not jobs:
        raise SystemExit(f"Prompts file has no jobs: {path}")
    return jobs, out_paths


def declared_png_outputs(job_dir: Path) -> list[Path]:
    doc = read_md(job_dir / "plan.md")
    outputs = normalize_str_list(doc.frontmatter.get("outputs"))
    out: list[Path] = []
    for rel in outputs:
        if str(rel).lower().endswith(".png"):
            out.append((job_dir / rel).resolve())
    return out


def image_dimensions(path: Path) -> tuple[str, str]:
    proc = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)], text=True, capture_output=True)
    if proc.returncode != 0:
        return "?", "?"
    width = "?"
    height = "?"
    for line in (proc.stdout or "").splitlines():
        m = re.search(r"pixelWidth:\s*([0-9]+)", line)
        if m:
            width = m.group(1)
        m = re.search(r"pixelHeight:\s*([0-9]+)", line)
        if m:
            height = m.group(1)
    return width, height


def write_verification(job_dir: Path, *, prompts_path: Path, out_dir: Path, key_source: str, files: list[Path], cmd: list[str]) -> None:
    vf = job_dir / "artifacts" / "verification.md"
    vf.parent.mkdir(parents=True, exist_ok=True)
    ts = now_iso()
    lines: list[str] = []
    if vf.exists():
        lines.append(vf.read_text(encoding="utf-8", errors="ignore").rstrip())
        lines.append("")
    else:
        lines.append("# Verification")
        lines.append("")
    lines.append(f"## {ts} imagegen_job")
    lines.append("")
    lines.append(f"- prompts: `{prompts_path}`")
    lines.append(f"- out_dir: `{out_dir}`")
    lines.append(f"- key source: `{key_source}`")
    lines.append(f"- command: `{' '.join(cmd)}`")
    lines.append("- spot-check: verify legibility at PDF scale (no dense tiny text).")
    lines.append("- generated files:")
    for p in sorted(files):
        w, h = image_dimensions(p)
        lines.append(f"  - `{p}` ({w}x{h})")
    vf.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run TheWorkshop image generation for a WI job via imagegen + apple-keychain.")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--work-item-id", required=True, help="WI-... to run image generation for")
    parser.add_argument(
        "--prompts",
        default="artifacts/prompts.jsonl",
        help="Prompts JSONL path (default: artifacts/prompts.jsonl relative to job dir)",
    )
    parser.add_argument(
        "--out-dir",
        default="outputs/images",
        help="Output image directory (default: outputs/images relative to job dir)",
    )
    parser.add_argument(
        "--mirror-project",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Mirror generated PNGs to <project>/outputs/images (default: true)",
    )
    parser.add_argument("--approve", default="ttl:1h", help="apple-keychain approval mode (default: ttl:1h)")
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs and print intended execution only")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    job_dir = find_job_dir(project_root, args.work_item_id.strip())

    prompts_path = Path(args.prompts).expanduser()
    if not prompts_path.is_absolute():
        prompts_path = (job_dir / prompts_path).resolve()
    out_dir = Path(args.out_dir).expanduser()
    if not out_dir.is_absolute():
        out_dir = (job_dir / out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    jobs, prompt_out_paths = parse_prompts_jsonl(prompts_path, out_dir)
    declared_pngs = declared_png_outputs(job_dir)

    code_home = codex_home()
    imagegen_cli = code_home / "skills" / "imagegen" / "scripts" / "image_gen.py"
    keychain_runner = code_home / "skills" / "apple-keychain" / "scripts" / "keychain_run.sh"
    if not imagegen_cli.exists():
        raise SystemExit(f"Missing imagegen CLI: {imagegen_cli}")
    if not keychain_runner.exists():
        raise SystemExit(f"Missing apple-keychain runner: {keychain_runner}")

    uv_bin = shutil.which("uv")
    if uv_bin:
        image_cmd = [
            uv_bin,
            "run",
            "--with",
            "openai",
            "--with",
            "pillow",
            "python3",
            str(imagegen_cli),
            "generate-batch",
            "--input",
            str(prompts_path),
            "--out-dir",
            str(out_dir),
        ]
    else:
        image_cmd = [
            sys.executable,
            str(imagegen_cli),
            "generate-batch",
            "--input",
            str(prompts_path),
            "--out-dir",
            str(out_dir),
        ]

    key_source = "env"
    run_cmd = image_cmd
    no_keychain = str(os.environ.get("THEWORKSHOP_NO_KEYCHAIN") or "").strip() == "1"
    if not no_keychain:
        service = preferred_keychain_service()
        if not service:
            raise SystemExit(
                "No matching Keychain item found for service `OPENAI_KEY` (or fallback `OPENAI_API_KEY`). "
                "Add OPENAI_KEY to macOS Keychain and retry."
            )
        key_source = f"keychain:{service}"
        run_cmd = [
            str(keychain_runner),
            "run",
            "--type",
            "generic",
            "--service",
            service,
            "--match",
            "--env",
            "OPENAI_API_KEY",
            "--approve",
            str(args.approve),
            "--",
        ] + image_cmd

    declared_display = [str(p) for p in declared_pngs]
    prompt_display = [str(p) for p in prompt_out_paths]
    print(f"job_dir={job_dir}")
    print(f"prompts={prompts_path}")
    print(f"out_dir={out_dir}")
    print(f"jobs={len(jobs)}")
    if declared_display:
        print("declared_png_outputs:")
        for p in declared_display:
            print(f"- {p}")
    if prompt_display:
        print("prompt_out_paths:")
        for p in prompt_display:
            print(f"- {p}")
    if args.dry_run:
        print("dry_run=1")
        print("command=" + " ".join(run_cmd))
        return

    run_env = dict(os.environ)
    if not no_keychain and "CODEX_KEYCHAIN_DIALOG_TIMEOUT" not in run_env:
        # Fail fast in headless/stuck-dialog contexts instead of hanging indefinitely.
        run_env["CODEX_KEYCHAIN_DIALOG_TIMEOUT"] = "30s"

    proc = subprocess.run(run_cmd, text=True, capture_output=True, env=run_env)
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.returncode != 0:
        raise SystemExit(
            "image generation failed:\n"
            f"  exit={proc.returncode}\n"
            f"  stdout:\n{proc.stdout}\n"
            f"  stderr:\n{proc.stderr}\n"
        )

    expected = {p.resolve() for p in declared_pngs + prompt_out_paths}
    if not expected:
        for p in out_dir.glob("*.png"):
            expected.add(p.resolve())
    missing = [p for p in sorted(expected) if not file_exists_nonempty(p)]
    if missing:
        raise SystemExit("Missing/empty expected image outputs:\n- " + "\n- ".join(str(p) for p in missing))

    generated = sorted(expected)
    if args.mirror_project and generated:
        dst_dir = project_root / "outputs" / "images"
        dst_dir.mkdir(parents=True, exist_ok=True)
        for src in generated:
            shutil.copy2(src, dst_dir / src.name)

    write_verification(
        job_dir,
        prompts_path=prompts_path,
        out_dir=out_dir,
        key_source=key_source,
        files=generated,
        cmd=run_cmd,
    )

    print(f"generated={len(generated)}")
    for p in generated:
        print(str(p))


if __name__ == "__main__":
    main()
