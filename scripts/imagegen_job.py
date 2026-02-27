#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from twlib import codex_home, normalize_str_list, now_iso, read_md, resolve_project_root


THEWORKSHOP_IMAGEGEN_API_KEY = "THEWORKSHOP_IMAGEGEN_API_KEY"
THEWORKSHOP_IMAGEGEN_CREDENTIAL_SOURCE = "THEWORKSHOP_IMAGEGEN_CREDENTIAL_SOURCE"
THEWORKSHOP_KEYCHAIN_RUNNER = "THEWORKSHOP_KEYCHAIN_RUNNER"
THEWORKSHOP_KEYCHAIN_SERVICE = "THEWORKSHOP_KEYCHAIN_SERVICE"
THEWORKSHOP_KEYCHAIN_SERVICES = "THEWORKSHOP_KEYCHAIN_SERVICES"
THEWORKSHOP_NO_KEYCHAIN = "THEWORKSHOP_NO_KEYCHAIN"

CANONICAL_IMAGEGEN_PROVIDER_DEFAULT = "auto"
OPENAI_IMAGEGEN_ENV_KEYS = (THEWORKSHOP_IMAGEGEN_API_KEY, "OPENAI_API_KEY", "OPENAI_KEY")
KEYCHAIN_SERVICE_DEFAULTS = ("OPENAI_KEY", "OPENAI_API_KEY")
OPENAI_IMAGE_KEY = "OPENAI_API_KEY"


@dataclass
class CredentialResolution:
    provider: str
    source: str
    command_prefix: list[str]
    env_overrides: dict[str, str]


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


def _env_value(env: Mapping[str, str], key: str) -> str:
    return str(env.get(key, "")).strip()


def _parse_service_list(env: Mapping[str, str]) -> list[str]:
    explicit = _env_value(env, THEWORKSHOP_KEYCHAIN_SERVICES) or _env_value(env, THEWORKSHOP_KEYCHAIN_SERVICE)
    if explicit:
        services = [svc.strip() for svc in explicit.replace(";", ",").replace("|", ",").split(",")]
        services = [svc for svc in services if svc]
        if services:
            return services
    return list(KEYCHAIN_SERVICE_DEFAULTS)


def resolve_keychain_runner(env: Mapping[str, str] | None = None) -> Path:
    env_root = dict(os.environ) if env is None else dict(env)
    override = env_root.get(THEWORKSHOP_KEYCHAIN_RUNNER, "").strip()
    if override:
        return Path(override).expanduser()
    return codex_home() / "skills" / "apple-keychain" / "scripts" / "keychain_run.sh"


def check_keychain_available(runner: Path | None = None, *, env: Mapping[str, str] | None = None) -> bool:
    candidate = runner or resolve_keychain_runner(env)
    if not candidate.exists():
        return False
    if not shutil.which("security"):
        return False
    return True


def keychain_service_exists(service: str, *, env: Mapping[str, str] | None = None) -> bool:
    if not check_keychain_available(env=env):
        return False
    proc = subprocess.run(
        ["security", "find-generic-password", "-s", service],
        text=True,
        capture_output=True,
        env=dict(os.environ | dict(env or {})),
    )
    return int(proc.returncode) == 0


def preferred_keychain_service(env: Mapping[str, str] | None = None) -> str | None:
    for service in _parse_service_list(dict(os.environ) if env is None else dict(env)):
        if keychain_service_exists(service, env=env):
            return service
    return None


def resolve_env_credential_source(env: Mapping[str, str] | None = None) -> tuple[str, str] | None:
    env_root = dict(os.environ) if env is None else dict(env)
    for key in OPENAI_IMAGEGEN_ENV_KEYS:
        value = _env_value(env_root, key)
        if value:
            return key, value
    return None


def resolve_imagegen_credential_provider(
    requested_provider: str = CANONICAL_IMAGEGEN_PROVIDER_DEFAULT,
    *,
    approve: str = "ttl:1h",
    no_keychain: bool = False,
    env: Mapping[str, str] | None = None,
) -> CredentialResolution:
    requested = (requested_provider or CANONICAL_IMAGEGEN_PROVIDER_DEFAULT).strip().lower()
    if requested not in {"auto", "env", "keychain"}:
        requested = CANONICAL_IMAGEGEN_PROVIDER_DEFAULT

    env_root = dict(os.environ) if env is None else dict(env)
    credential = resolve_env_credential_source(env_root)
    if requested in {"auto", "env"} and credential:
        key_name, key_value = credential
        return CredentialResolution(
            provider="env",
            source=f"env:{key_name}",
            command_prefix=[],
            env_overrides={
                OPENAI_IMAGE_KEY: key_value,
                "CODEX_ALLOW_DIRECT_OPENAI_KEY": "1",
            },
        )

    if requested == "env":
        raise SystemExit(
            "Missing image credentials for env mode. Set "
            f"{THEWORKSHOP_IMAGEGEN_API_KEY} (recommended), "
            f"or legacy {OPENAI_IMAGEGEN_ENV_KEYS[1]} / {OPENAI_IMAGEGEN_ENV_KEYS[2]}."
        )

    if no_keychain:
        raise SystemExit(
            "Image credentials unavailable (no env key and keychain disabled with "
            f"{THEWORKSHOP_NO_KEYCHAIN}=1).\n"
            f"Set {THEWORKSHOP_IMAGEGEN_API_KEY} (recommended) for CI/headless-safe execution."
        )

    runner = resolve_keychain_runner(env_root)
    if not check_keychain_available(runner, env=env_root):
        raise SystemExit(
            "No usable keychain path found for image credentials.\n"
            "Set "
            f"{THEWORKSHOP_IMAGEGEN_API_KEY} (recommended), "
            f"or install/configure optional keychain support (`apple-keychain`)."
        )

    service = preferred_keychain_service(env_root)
    if not service:
        defaults = ", ".join(_parse_service_list(env_root))
        raise SystemExit(
            "No matching keychain item found for image credentials. "
            f"Checked services: {defaults}\n"
            f"Install one of these services in Apple Keychain and retry, "
            f"or set {THEWORKSHOP_IMAGEGEN_API_KEY}."
        )

    return CredentialResolution(
        provider="keychain",
        source=f"keychain:{service}",
        command_prefix=[
            str(runner),
            "run",
            "--type",
            "generic",
            "--service",
            service,
            "--match",
            "--env",
            OPENAI_IMAGE_KEY,
            "--approve",
            str(approve),
            "--",
        ],
        env_overrides={},
    )


def build_imagegen_run_env(
    *,
    provider: str,
    source: str,
    overrides: dict[str, str],
    base_env: Mapping[str, str] | None = None,
    no_keychain: bool = False,
) -> dict[str, str]:
    run_env = dict(os.environ) if base_env is None else dict(base_env)
    run_env[THEWORKSHOP_IMAGEGEN_CREDENTIAL_SOURCE] = source
    run_env.update(overrides)
    if provider == "keychain" and not no_keychain and "CODEX_KEYCHAIN_DIALOG_TIMEOUT" not in run_env:
        # Fail fast in headless/stuck-dialog contexts instead of hanging indefinitely.
        run_env["CODEX_KEYCHAIN_DIALOG_TIMEOUT"] = "30s"
    return run_env


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


def write_verification(
    job_dir: Path,
    *,
    prompts_path: Path,
    out_dir: Path,
    key_source: str,
    files: list[Path],
    cmd: list[str],
) -> None:
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
    parser = argparse.ArgumentParser(description="Run TheWorkshop image generation for a WI job.")
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
    parser.add_argument(
        "--approve",
        default="ttl:1h",
        help="keychain runner approval mode (applies only when keychain provider is selected)",
    )
    parser.add_argument(
        "--credential-provider",
        default=os.environ.get(THEWORKSHOP_IMAGEGEN_CREDENTIAL_SOURCE, CANONICAL_IMAGEGEN_PROVIDER_DEFAULT),
        choices=["auto", "env", "keychain"],
        help="Credential mode for image API access: env/keychain/auto.",
    )
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

    imagegen_cli = codex_home() / "skills" / "imagegen" / "scripts" / "image_gen.py"

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

    no_keychain = _env_value(os.environ, THEWORKSHOP_NO_KEYCHAIN) == "1"
    resolution = resolve_imagegen_credential_provider(
        args.credential_provider,
        approve=args.approve,
        no_keychain=no_keychain,
    )
    run_cmd = resolution.command_prefix + image_cmd

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
        print(f"credential_source={resolution.source}")
        return

    if not imagegen_cli.exists():
        raise SystemExit(f"Missing imagegen CLI: {imagegen_cli}")

    run_env = build_imagegen_run_env(
        provider=resolution.provider,
        source=resolution.source,
        overrides=resolution.env_overrides,
        base_env=os.environ,
        no_keychain=no_keychain,
    )

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
        key_source=resolution.source,
        files=generated,
        cmd=run_cmd,
    )

    print(f"generated={len(generated)}")
    for p in generated:
        print(str(p))


if __name__ == "__main__":
    main()
