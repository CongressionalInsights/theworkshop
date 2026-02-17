#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from twlib import (
    detect_github_repo,
    ensure_dir,
    kebab,
    list_job_dirs,
    list_workstream_dirs,
    load_job,
    load_workstream,
    now_iso,
    read_md,
    resolve_project_root,
    run_gh,
    write_md,
)


STATUS_LABELS = {
    "planned": {"color": "6b7280", "description": "TheWorkshop status: planned"},
    "in_progress": {"color": "b45f06", "description": "TheWorkshop status: in_progress"},
    "blocked": {"color": "b42318", "description": "TheWorkshop status: blocked"},
    "done": {"color": "027a48", "description": "TheWorkshop status: done"},
    "cancelled": {"color": "7a1f5c", "description": "TheWorkshop status: cancelled"},
}


def gh_json(args: list[str], repo: str) -> object:
    res = run_gh(args + ["--json", "number,title,url,state,name"], repo=repo)
    return json.loads(res.stdout) if res.stdout.strip() else []


def ensure_labels(repo: str, workstreams: list[tuple[str, str]]) -> None:
    # workstreams: [(ws_id, ws_title)]
    existing = run_gh(["label", "list", "--limit", "500", "--json", "name"], repo=repo)
    existing_names = set()
    try:
        existing_names = set([x.get("name") for x in json.loads(existing.stdout)])
    except Exception:
        pass

    needed = []
    for status, meta in STATUS_LABELS.items():
        needed.append((f"status:{status}", meta["color"], meta["description"]))
    for ws_id, ws_title in workstreams:
        slug = kebab(ws_title)[:32]
        needed.append((f"ws:{slug}", "0f6b5d", f"TheWorkshop workstream {ws_id}: {ws_title}"))

    for name, color, desc in needed:
        if name in existing_names:
            continue
        run_gh(["label", "create", name, "--color", color, "--description", desc], repo=repo)


def load_or_init_map(project_root: Path, repo: str, enabled: bool) -> dict:
    ensure_dir(project_root / "notes")
    path = project_root / "notes" / "github-map.json"
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("schema") == "theworkshop.githubmap.v1":
                return payload
        except Exception:
            pass
    return {
        "schema": "theworkshop.githubmap.v1",
        "repo": repo,
        "enabled": enabled,
        "last_sync_at": "",
        "issues": {},
        "milestones": {},
        "project_board": {"id": "", "url": ""},
    }


def write_map(project_root: Path, payload: dict) -> None:
    path = project_root / "notes" / "github-map.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def issue_body(project_root: Path, job_dir: Path) -> str:
    doc = read_md(job_dir / "plan.md")
    fm = doc.frontmatter
    wi = fm.get("work_item_id", "")
    title = fm.get("title", "")
    status = fm.get("status", "")
    return "\n".join(
        [
            f"Work Item: {wi}",
            f"Title: {title}",
            f"Status: {status}",
            "",
            "On disk:",
            f"- {job_dir.relative_to(project_root)}/plan.md",
            f"- {job_dir.relative_to(project_root)}/prompt.md",
            "",
            "Acceptance + verification live in the job plan.",
        ]
    )


def find_existing_issue(repo: str, wi: str) -> dict | None:
    search = f'\"[{wi}]\" in:title'
    res = run_gh(["issue", "list", "--search", search, "--limit", "10", "--json", "number,title,url,state"], repo=repo)
    try:
        items = json.loads(res.stdout)
    except Exception:
        return None
    for it in items or []:
        if str(it.get("title", "")).startswith(f"[{wi}]"):
            return it
    return None


def gh_api_json(method: str, endpoint: str, fields: list[tuple[str, str]] | None = None, *, paginate: bool = False) -> object:
    cmd = ["api", "-X", method, endpoint]
    if paginate:
        cmd.append("--paginate")
    for k, v in (fields or []):
        cmd.extend(["-f", f"{k}={v}"])
    res = run_gh(cmd, repo=None)
    return json.loads(res.stdout) if res.stdout.strip() else {}


def load_waves(project_root: Path) -> list[dict]:
    proj = read_md(project_root / "plan.md")
    waves = proj.frontmatter.get("waves", []) or []
    if isinstance(waves, dict):
        return [waves]
    out = []
    for w in waves if isinstance(waves, list) else []:
        if isinstance(w, dict):
            out.append(w)
    return out


def list_milestones(repo: str) -> list[dict]:
    # GitHub REST returns a list; paginate to include older milestones.
    endpoint = f"repos/{repo}/milestones?state=all"
    payload = gh_api_json("GET", endpoint, paginate=True)
    return payload if isinstance(payload, list) else []


def ensure_milestones(repo: str, waves: list[dict], gm: dict, dry_run: bool) -> dict[str, dict]:
    existing = list_milestones(repo)
    by_title = {m.get("title", ""): m for m in existing}

    milestones = gm.get("milestones", {}) or {}
    for w in waves:
        wid = str(w.get("id") or "").strip()
        if not wid:
            continue
        title = str(w.get("title") or "").strip() or wid
        gh_title = f"{wid} {title}".strip()
        if wid in milestones and milestones[wid].get("number"):
            continue
        if gh_title in by_title:
            m = by_title[gh_title]
            milestones[wid] = {"number": m.get("number"), "url": m.get("html_url") or m.get("url"), "title": gh_title}
            continue
        if dry_run:
            milestones[wid] = {"number": "", "url": "", "title": gh_title}
            continue

        fields = [("title", gh_title), ("description", f"TheWorkshop wave {wid}")]
        end = str(w.get("end") or "").strip()
        if end:
            # GitHub expects RFC3339 timestamp for due_on.
            fields.append(("due_on", f"{end}T23:59:59Z"))
        created = gh_api_json("POST", f"repos/{repo}/milestones", fields)
        if isinstance(created, dict):
            milestones[wid] = {
                "number": created.get("number"),
                "url": created.get("html_url") or created.get("url"),
                "title": gh_title,
            }
    return milestones


def ensure_issue(repo: str, project_root: Path, ws_title: str, job: object, gm: dict, milestone_number: int | None, dry_run: bool) -> dict:
    wi = job.work_item_id
    issues = gm.get("issues", {}) or {}
    if wi in issues and issues[wi].get("number"):
        return issues[wi]

    existing = find_existing_issue(repo, wi)
    if existing:
        return {"number": existing.get("number"), "url": existing.get("url")}

    if dry_run:
        return {"number": "", "url": ""}

    title = f"[{wi}] {job.title}"
    body = issue_body(project_root, job.path)
    ws_slug = kebab(ws_title)[:32]
    labels = [f"ws:{ws_slug}", f"status:{job.status}"]

    fields: list[tuple[str, str]] = [("title", title), ("body", body)]
    for lab in labels:
        fields.append(("labels[]", lab))
    if milestone_number is not None:
        fields.append(("milestone", str(milestone_number)))
    created = gh_api_json("POST", f"repos/{repo}/issues", fields)
    if isinstance(created, dict):
        return {"number": created.get("number"), "url": created.get("html_url") or created.get("url")}
    return {"number": "", "url": ""}


def sync_issue(repo: str, project_root: Path, ws_title: str, job, issue: dict, milestone_number: int | None, dry_run: bool) -> None:
    num = issue.get("number")
    if not num:
        return
    ws_slug = kebab(ws_title)[:32]
    desired_labels = [f"ws:{ws_slug}", f"status:{job.status}"]

    if dry_run:
        return

    body = issue_body(project_root, job.path)
    fields: list[tuple[str, str]] = [("body", body)]
    for lab in desired_labels:
        fields.append(("labels[]", lab))
    if milestone_number is not None:
        fields.append(("milestone", str(milestone_number)))
    gh_api_json("PATCH", f"repos/{repo}/issues/{num}", fields)

    if job.status == "done":
        gh_api_json("PATCH", f"repos/{repo}/issues/{num}", [("state", "closed")])


def maybe_create_project_board(repo: str, title: str) -> dict:
    # Best-effort: if gh project commands are unavailable or fail, return empty.
    try:
        res = subprocess.run(["gh", "project", "create", "--owner", repo.split("/")[0], "--title", title], check=True, capture_output=True, text=True)
        url = res.stdout.strip().splitlines()[-1] if res.stdout.strip() else ""
        return {"id": "", "url": url}
    except Exception:
        return {"id": "", "url": ""}


def main() -> None:
    parser = argparse.ArgumentParser(description="Mirror/sync TheWorkshop project into GitHub (opt-in).")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--repo", help="owner/repo (overrides detection)")
    parser.add_argument("--enable", action="store_true", help="Enable GitHub mirroring in project plan")
    parser.add_argument("--dry-run", action="store_true", help="Do not create/edit GitHub artifacts")
    parser.add_argument("--with-project-board", action="store_true", help="Attempt to create a GitHub Project board (best-effort)")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    proj_path = project_root / "plan.md"
    proj = read_md(proj_path)

    repo = args.repo or str(proj.frontmatter.get("github_repo") or "").strip()
    if not repo:
        detected = detect_github_repo(project_root)
        if detected:
            repo = detected

    if not repo:
        raise SystemExit("GitHub repo not specified and could not be detected. Pass --repo owner/repo.")

    enabled = bool(proj.frontmatter.get("github_enabled"))
    if args.enable and not enabled:
        proj.frontmatter["github_enabled"] = True
        proj.frontmatter["github_repo"] = repo
        proj.frontmatter["updated_at"] = now_iso()
        write_md(proj_path, proj)
        enabled = True

    if not enabled:
        raise SystemExit("GitHub mirroring is not enabled for this project. Set github_enabled: true or run with --enable.")

    # Ensure auth (best effort; will fail later if not authed)
    if not args.dry_run:
        run_gh(["auth", "status"], repo=None)

    # Gather workstreams and jobs
    ws_items = []
    for ws_dir in list_workstream_dirs(project_root):
        ws = load_workstream(ws_dir)
        ws_items.append((ws, ws_dir))

    ensure_labels(repo, [(ws.id, ws.title) for ws, _ in ws_items])

    gm = load_or_init_map(project_root, repo, enabled=True)
    gm["repo"] = repo

    # Waves -> milestones (best-effort)
    waves = load_waves(project_root)
    gm["milestones"] = ensure_milestones(repo, waves, gm, dry_run=args.dry_run)
    milestone_map = {k: v for k, v in (gm.get("milestones", {}) or {}).items() if isinstance(v, dict)}

    if args.with_project_board and not gm.get("project_board", {}).get("url"):
        board_title = f"{proj.frontmatter.get('id','')} {proj.frontmatter.get('title','')}"
        gm["project_board"] = maybe_create_project_board(repo, board_title)

    # Issues: ensure and sync
    issues_map = gm.get("issues", {}) or {}

    for ws, _ws_dir in ws_items:
        for job_dir in list_job_dirs(ws.path):
            job = load_job(job_dir)
            ms_num = None
            if job.wave_id and job.wave_id in milestone_map:
                try:
                    ms_num = int(milestone_map[job.wave_id].get("number") or 0) or None
                except Exception:
                    ms_num = None
            issue = ensure_issue(repo, project_root, ws.title, job, gm, ms_num, dry_run=args.dry_run)
            if issue.get("number") or issue.get("url"):
                issues_map[job.work_item_id] = issue
            sync_issue(repo, project_root, ws.title, job, issue, ms_num, dry_run=args.dry_run)

            # Update job plan with issue metadata (control plane)
            if issue.get("number") or issue.get("url"):
                jd = read_md(job_dir / "plan.md")
                if issue.get("number"):
                    jd.frontmatter["github_issue_number"] = str(issue.get("number"))
                if issue.get("url"):
                    jd.frontmatter["github_issue_url"] = str(issue.get("url"))
                jd.frontmatter["updated_at"] = now_iso()
                write_md(job_dir / "plan.md", jd)

    gm["issues"] = issues_map
    gm["last_sync_at"] = now_iso()
    write_map(project_root, gm)

    print(str(project_root / "notes" / "github-map.json"))


if __name__ == "__main__":
    main()
