#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from imagegen_job import (
    THEWORKSHOP_NO_KEYCHAIN,
    build_imagegen_run_env,
    resolve_imagegen_credential_provider,
)
from runtime_profile import skill_script_path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "docs" / "assets" / "prompts.jsonl"
DEFAULT_OUT_DIR = REPO_ROOT / "docs" / "assets"
DEFAULT_OPENAI_MODEL = "gpt-image-1.5"


def _env_flag(name: str) -> str:
    return str(os.environ.get(name, "")).strip()


def _load_jobs(path: Path) -> list[dict]:
    jobs: list[dict] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        obj = json.loads(line)
        if not isinstance(obj, dict):
            raise SystemExit(f"Manifest line {line_no} must be a JSON object.")
        if not str(obj.get("prompt", "")).strip():
            raise SystemExit(f"Manifest line {line_no} is missing a non-empty prompt.")
        jobs.append(obj)
    if not jobs:
        raise SystemExit(f"No asset jobs found in {path}")
    return jobs


def _filter_jobs(jobs: list[dict], asset_names: set[str]) -> list[dict]:
    if not asset_names:
        return jobs
    filtered = [job for job in jobs if str(job.get("asset", "")).strip() in asset_names]
    if not filtered:
        wanted = ", ".join(sorted(asset_names))
        raise SystemExit(f"No manifest jobs matched --asset values: {wanted}")
    return filtered


def _write_temp_manifest(jobs: list[dict]) -> Path:
    tmp = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".jsonl", delete=False)
    try:
        for job in jobs:
            tmp.write(json.dumps(job, ensure_ascii=True) + "\n")
    finally:
        tmp.close()
    return Path(tmp.name)


def _run_openai(run_manifest: Path, out_dir: Path, args: argparse.Namespace) -> int:
    imagegen_cli = skill_script_path("imagegen", "scripts/image_gen.py")
    if not imagegen_cli.exists():
        raise SystemExit(f"Missing imagegen CLI: {imagegen_cli}")

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
        ]
    else:
        image_cmd = [sys.executable, str(imagegen_cli), "generate-batch"]

    image_cmd.extend(
        [
            "--input",
            str(run_manifest),
            "--out-dir",
            str(out_dir),
            "--concurrency",
            str(args.concurrency),
            "--model",
            args.openai_model,
        ]
    )
    if args.force:
        image_cmd.append("--force")
    if args.dry_run:
        image_cmd.append("--dry-run")

    no_keychain = _env_flag(THEWORKSHOP_NO_KEYCHAIN) == "1"
    resolution = resolve_imagegen_credential_provider(
        args.credential_provider,
        approve=args.approve,
        no_keychain=no_keychain,
        env=os.environ,
    )
    run_env = build_imagegen_run_env(
        provider=resolution.provider,
        source=resolution.source,
        overrides=resolution.env_overrides,
        base_env=os.environ,
        no_keychain=no_keychain,
    )
    run_cmd = resolution.command_prefix + image_cmd
    print(f"credential_source={resolution.source}")
    print("command=" + " ".join(run_cmd))
    return subprocess.run(run_cmd, text=True, env=run_env).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the public docs image assets for TheWorkshop.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="JSONL manifest of docs assets to generate.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR), help="Output directory for generated assets.")
    parser.add_argument("--asset", action="append", default=[], help="Asset name from manifest to generate. Repeatable.")
    parser.add_argument("--openai-model", default=DEFAULT_OPENAI_MODEL, help="OpenAI image model for docs-asset generation.")
    parser.add_argument("--approve", default="ttl:1h", help="apple-keychain approval mode when keychain is used.")
    parser.add_argument(
        "--credential-provider",
        default=os.environ.get("THEWORKSHOP_IMAGEGEN_CREDENTIAL_SOURCE", "auto"),
        choices=["auto", "env", "keychain"],
        help="Credential mode for image API access.",
    )
    parser.add_argument("--concurrency", type=int, default=3, help="Concurrent image jobs for generate-batch.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing generated outputs.")
    parser.add_argument("--dry-run", action="store_true", help="Print the intended imagegen invocation without calling the API.")
    args = parser.parse_args()

    manifest_path = Path(args.manifest).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    if not manifest_path.exists():
        raise SystemExit(f"Manifest not found: {manifest_path}")
    out_dir.mkdir(parents=True, exist_ok=True)

    jobs = _load_jobs(manifest_path)
    jobs = _filter_jobs(jobs, {token.strip() for token in args.asset if token.strip()})
    run_manifest = _write_temp_manifest(jobs)

    imagegen_cli = skill_script_path("imagegen", "scripts/image_gen.py")
    if not imagegen_cli.exists():
        raise SystemExit(f"Missing imagegen CLI: {imagegen_cli}")

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
        ]
    else:
        image_cmd = [sys.executable, str(imagegen_cli), "generate-batch"]

    image_cmd.extend(
        [
            "--input",
            str(run_manifest),
            "--out-dir",
            str(out_dir),
            "--concurrency",
            str(args.concurrency),
        ]
    )
    if args.force:
        image_cmd.append("--force")
    if args.dry_run:
        image_cmd.append("--dry-run")

    no_keychain = _env_flag(THEWORKSHOP_NO_KEYCHAIN) == "1"
    resolution = resolve_imagegen_credential_provider(
        args.credential_provider,
        approve=args.approve,
        no_keychain=no_keychain,
        env=os.environ,
    )
    run_env = build_imagegen_run_env(
        provider=resolution.provider,
        source=resolution.source,
        overrides=resolution.env_overrides,
        base_env=os.environ,
        no_keychain=no_keychain,
    )
    run_cmd = resolution.command_prefix + image_cmd

    print(f"manifest={manifest_path}")
    print(f"run_manifest={run_manifest}")
    print(f"out_dir={out_dir}")
    print(f"jobs={len(jobs)}")

    try:
        rc = _run_openai(run_manifest, out_dir, args)
    finally:
        try:
            run_manifest.unlink()
        except FileNotFoundError:
            pass

    if rc != 0:
        raise SystemExit(rc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
