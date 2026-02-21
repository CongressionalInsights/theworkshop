#!/usr/bin/env python3
from __future__ import annotations

import os
import platform
import struct
import subprocess
import sys
import tempfile
import zlib
import shutil
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from twlib import now_iso  # noqa: E402
from twyaml import join_frontmatter, split_frontmatter  # noqa: E402


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


def set_frontmatter(path: Path, **updates) -> None:
    doc = split_frontmatter(path.read_text(encoding="utf-8", errors="ignore"))
    for k, v in updates.items():
        doc.frontmatter[k] = v
    path.write_text(join_frontmatter(doc), encoding="utf-8")


def replace_section(body: str, heading: str, new_lines: list[str]) -> str:
    lines = body.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.strip() == heading.strip():
            start = i
            break
    if start is None:
        return body.rstrip() + "\n\n" + heading + "\n\n" + "\n".join(new_lines).rstrip() + "\n"

    end = len(lines)
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("# "):
            end = i
            break

    out = lines[: start + 1]
    out.append("")
    out.extend(new_lines)
    out.append("")
    out.extend(lines[end:])
    return "\n".join(out).rstrip() + "\n"


def write_png(path: Path, width: int, height: int, rgb: tuple[int, int, int]) -> None:
    # Minimal truecolor PNG encoder (no alpha, no interlace).
    r, g, b = rgb
    row = b"\x00" + bytes([r, g, b]) * width
    raw = row * height
    compressed = zlib.compress(raw, level=9)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", compressed) + chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


def find_job_dir(project_root: Path, wi: str) -> Path:
    matches = list(project_root.glob(f"workstreams/WS-*/jobs/{wi}-*"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one job dir for {wi}, got {len(matches)}")
    return matches[0]


def patch_job_plan(job_plan: Path, wi: str) -> None:
    doc = split_frontmatter(job_plan.read_text(encoding="utf-8", errors="ignore"))
    doc.frontmatter["outputs"] = [
        "outputs/manual.css",
        "outputs/doc.html",
        "outputs/doc.pdf",
        "outputs/images/cover.png",
        "outputs/images/diagram.png",
    ]
    doc.frontmatter["verification_evidence"] = [
        "artifacts/verification.md",
        "artifacts/pdfimages.txt",
    ]
    doc.body = replace_section(doc.body, "# Objective", ["Build PDF and verify embedded images are true assets."])
    doc.body = replace_section(
        doc.body,
        "# Outputs",
        [
            "- `outputs/manual.css`",
            "- `outputs/doc.html`",
            "- `outputs/doc.pdf`",
            "- `outputs/images/cover.png`",
            "- `outputs/images/diagram.png`",
        ],
    )
    doc.body = replace_section(
        doc.body,
        "# Acceptance Criteria",
        [
            "- All declared outputs and evidence exist and are non-empty.",
            "- The PDF embeds expected large image assets.",
            f"- Output includes `<promise>{wi}-DONE</promise>`.",
        ],
    )
    doc.body = replace_section(
        doc.body,
        "# Verification",
        [
            "- Build the PDF via headless Chrome.",
            "- Capture `pdfimages -list` into `artifacts/pdfimages.txt`.",
            "- Write verification note into `artifacts/verification.md`.",
        ],
    )
    job_plan.write_text(join_frontmatter(doc), encoding="utf-8")


def read_frontmatter(path: Path) -> dict:
    return split_frontmatter(path.read_text(encoding="utf-8", errors="ignore")).frontmatter


def resolve_pdf_browser() -> tuple[Path | None, str]:
    candidate_names = [
        os.environ.get("THEWORKSHOP_PDF_BROWSER"),
        os.environ.get("THEWORKSHOP_CHROME_PATH"),
        "chrome",
        "google-chrome",
        "google-chrome-stable",
        "microsoft-edge",
        "chromium",
        "chromium-browser",
        "msedge",
    ]

    # Common app-bundle binaries on macOS.
    if platform.system().lower().startswith("darwin"):
        candidate_names = [
            os.environ.get("THEWORKSHOP_PDF_BROWSER"),
            os.environ.get("THEWORKSHOP_CHROME_PATH"),
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome Canary",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ] + candidate_names

    seen = set()
    for raw in candidate_names:
        if not raw:
            continue
        if raw in seen:
            continue
        seen.add(raw)
        path = Path(raw).expanduser()
        if path.exists() and os.access(str(path), os.X_OK):
            return path, "explicit/bundled path"
        which = shutil.which(raw)
        if which:
            return Path(which), "PATH"
    return None, "No Chrome/Chromium executable found. Set THEWORKSHOP_PDF_BROWSER or THEWORKSHOP_CHROME_PATH."


def required_tools_available() -> tuple[bool, str, Path | None]:
    if platform.system().lower().startswith("darwin"):
        os_id = "darwin"
    else:
        os_id = platform.system().lower() or "unknown"

    browser, source = resolve_pdf_browser()
    if browser is None:
        return (
            False,
            f"{source} (currently running on {os_id}; install Chromium/Chrome or set THEWORKSHOP_PDF_BROWSER)",
            None,
        )

    if not shutil.which("pdfimages"):
        return False, "Missing required command in PATH: pdfimages", None

    return True, f"pdf_browser={browser} ({source})", browser


def main() -> None:
    tmp = tempfile.TemporaryDirectory(prefix="theworkshop-truth-pdf-")
    base_dir = Path(tmp.name).resolve()
    ok, reason, browser = required_tools_available()
    if not ok:
        print(f"TRUTH GATE PDF TEST SKIPPED: {reason}")
        tmp.cleanup()
        return

    try:
        proj = run(py("project_new.py") + ["--name", "Truth PDF Test", "--base-dir", str(base_dir)]).stdout.strip()
        project_root = Path(proj).resolve()
        ws = run(py("workstream_add.py") + ["--project", str(project_root), "--title", "WS"]).stdout.strip()
        wi = run(py("job_add.py") + ["--project", str(project_root), "--workstream", ws, "--title", "PDF Truth", "--stakes", "low"]).stdout.strip()

        set_frontmatter(
            project_root / "plan.md",
            agreement_status="agreed",
            agreed_at=now_iso(),
            agreed_notes="truth gate pdf test",
            updated_at=now_iso(),
        )

        job_dir = find_job_dir(project_root, wi)
        patch_job_plan(job_dir / "plan.md", wi)

        outputs = job_dir / "outputs"
        artifacts = job_dir / "artifacts"
        outputs.mkdir(parents=True, exist_ok=True)
        artifacts.mkdir(parents=True, exist_ok=True)
        (outputs / "images").mkdir(parents=True, exist_ok=True)

        write_png(outputs / "images" / "cover.png", 800, 1200, (20, 90, 150))
        write_png(outputs / "images" / "diagram.png", 1200, 800, (130, 30, 80))
        (outputs / "manual.css").write_text("body { font-family: sans-serif; }\n", encoding="utf-8")

        # Intentionally reference missing image paths to force placeholder embeds while real assets still exist on disk.
        html = """
        <!doctype html>
        <html><head><meta charset=\"utf-8\"><link rel=\"stylesheet\" href=\"manual.css\"></head>
        <body>
          <h1>PDF Truth Test</h1>
          <img src=\"images/missing-cover.png\" alt=\"missing cover\" />
          <img src=\"images/missing-diagram.png\" alt=\"missing diagram\" />
          <p>Artifact truth test content.</p>
        </body></html>
        """.strip()
        (outputs / "doc.html").write_text(html + "\n", encoding="utf-8")

        run(
            [
                str(browser),
                "--headless",
                "--disable-gpu",
                "--virtual-time-budget=4000",
                "--run-all-compositor-stages-before-draw",
                "--allow-file-access-from-files",
                f"--print-to-pdf={outputs / 'doc.pdf'}",
                "--no-pdf-header-footer",
                f"file://{outputs / 'doc.html'}",
            ]
        )

        pdfimages = run(["pdfimages", "-list", str(outputs / "doc.pdf")])
        (artifacts / "pdfimages.txt").write_text(pdfimages.stdout, encoding="utf-8")
        (artifacts / "verification.md").write_text(
            "# Verification\n\nBuilt PDF and captured pdfimages output.\n",
            encoding="utf-8",
        )

        run(py("job_start.py") + ["--project", str(project_root), "--work-item-id", wi])
        failed = run(py("job_complete.py") + ["--project", str(project_root), "--work-item-id", wi], check=False)
        if failed.returncode == 0:
            raise RuntimeError("Expected job_complete to fail truth gate when PDF lacks expected embedded large images")

        fm = read_frontmatter(job_dir / "plan.md")
        if str(fm.get("status") or "") == "done":
            raise RuntimeError("Job should not be done when pdf_embeds_images truth check fails")
        if str(fm.get("truth_last_status") or "") != "fail":
            raise RuntimeError("Expected truth_last_status=fail after PDF truth failure")

        print("TRUTH GATE PDF TEST PASSED")
        print(str(project_root))
    finally:
        tmp.cleanup()


if __name__ == "__main__":
    main()
