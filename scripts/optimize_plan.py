#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import defaultdict, deque
from pathlib import Path

from twlib import list_job_dirs, list_workstream_dirs, now_iso, read_md, resolve_project_root


def extract_task_count(body: str) -> int:
    # Count "- [ ]" / "- [x]" items under "# Tasks" (best-effort).
    if "# Tasks" not in body:
        return 0
    section = body.split("# Tasks", 1)[1]
    lines = section.splitlines()
    count = 0
    for ln in lines[1:]:
        if ln.startswith("# "):
            break
        if ln.strip().startswith("- ["):
            count += 1
    return count


def topo_sort(nodes: list[str], edges: list[tuple[str, str]]) -> tuple[list[str], list[str]]:
    # edges: (src -> dst)
    indeg = {n: 0 for n in nodes}
    adj = defaultdict(list)
    for a, b in edges:
        if a not in indeg or b not in indeg:
            continue
        adj[a].append(b)
        indeg[b] += 1
    q = deque([n for n in nodes if indeg[n] == 0])
    out = []
    while q:
        n = q.popleft()
        out.append(n)
        for m in adj.get(n, []):
            indeg[m] -= 1
            if indeg[m] == 0:
                q.append(m)
    remaining = [n for n in nodes if n not in out]
    return out, remaining


def critical_path(order: list[str], edges: list[tuple[str, str]], weights: dict[str, float]) -> tuple[list[str], float]:
    preds = defaultdict(list)
    for a, b in edges:
        preds[b].append(a)

    dist: dict[str, float] = {n: weights.get(n, 1.0) for n in order}
    parent: dict[str, str | None] = {n: None for n in order}
    for n in order:
        best = weights.get(n, 1.0)
        best_parent = None
        for p in preds.get(n, []):
            if p not in dist:
                continue
            cand = dist[p] + weights.get(n, 1.0)
            if cand > best:
                best = cand
                best_parent = p
        dist[n] = best
        parent[n] = best_parent

    if not dist:
        return [], 0.0
    end = max(dist.keys(), key=lambda k: dist[k])
    total = dist[end]
    path = []
    cur: str | None = end
    while cur:
        path.append(cur)
        cur = parent.get(cur)
    path.reverse()
    return path, total


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate an optimization report for TheWorkshop plans (no mutation).")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--out", help="Output markdown path (default: outputs/optimize-report.md)")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    ts = now_iso()

    jobs = {}
    weights = {}
    tasks = {}
    deps_missing = []
    edges = []

    for ws_dir in list_workstream_dirs(project_root):
        for job_dir in list_job_dirs(ws_dir):
            doc = read_md(job_dir / "plan.md")
            fm = doc.frontmatter
            wi = str(fm.get("work_item_id") or "").strip()
            if not wi:
                continue
            jobs[wi] = {"dir": job_dir, "title": str(fm.get("title") or ""), "status": str(fm.get("status") or "")}
            try:
                weights[wi] = float(fm.get("estimate_hours") or 1.0)
            except Exception:
                weights[wi] = 1.0
            tasks[wi] = extract_task_count(doc.body)
            depends = fm.get("depends_on", []) or []
            if isinstance(depends, str):
                depends = [d.strip() for d in depends.split(",") if d.strip()]
            for d in depends:
                d = str(d).strip()
                if not d:
                    continue
                if d not in jobs:
                    deps_missing.append((wi, d))
                edges.append((d, wi))

    nodes = sorted(jobs.keys())
    order, remaining = topo_sort(nodes, edges)
    cp, cp_hours = critical_path(order, edges, weights) if not remaining else ([], 0.0)

    oversized = [wi for wi in nodes if weights.get(wi, 1.0) >= 6.0 or tasks.get(wi, 0) >= 10]
    tiny = [wi for wi in nodes if weights.get(wi, 1.0) <= 0.25 and tasks.get(wi, 0) <= 2]

    out_dir = project_root / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out).expanduser().resolve() if args.out else out_dir / "optimize-report.md"

    lines = []
    lines.append("# Optimization Report")
    lines.append("")
    lines.append(f"- Generated: {ts}")
    lines.append(f"- Jobs: {len(nodes)}")
    lines.append(f"- Edges: {len(edges)}")
    lines.append("")

    if remaining:
        lines.append("## Dependency Issues")
        lines.append("")
        lines.append("- Cycle detected or unresolved dependencies prevent topological ordering.")
        lines.append("- Remaining nodes:")
        for wi in remaining[:50]:
            lines.append(f"  - {wi} {jobs.get(wi, {}).get('title', '')}")
        lines.append("")
    else:
        lines.append("## Suggested Order (Topological)")
        lines.append("")
        for wi in order:
            lines.append(f"- {wi} ({weights.get(wi,1.0)}h) {jobs[wi]['title']}")
        lines.append("")

        lines.append("## Critical Path (Weighted by estimate_hours)")
        lines.append("")
        if cp:
            lines.append(f"- Total hours (critical path): {cp_hours:.2f}h")
            for wi in cp:
                lines.append(f"  - {wi} ({weights.get(wi,1.0)}h) {jobs[wi]['title']}")
        else:
            lines.append("- (none)")
        lines.append("")

    if deps_missing:
        lines.append("## Missing Dependency Targets (Best-Effort Detection)")
        lines.append("")
        for wi, dep in deps_missing[:50]:
            lines.append(f"- {wi} depends_on {dep} (not found in current scan)")
        lines.append("")

    lines.append("## Split Suggestions (Oversized Jobs)")
    lines.append("")
    if oversized:
        for wi in oversized:
            lines.append(f"- {wi} ({weights.get(wi,1.0)}h, tasks={tasks.get(wi,0)}): {jobs[wi]['title']}")
            lines.append("  - Suggestion: split into 2–4 smaller jobs with separate outputs + verification evidence.")
    else:
        lines.append("- (none)")
    lines.append("")

    lines.append("## Merge Suggestions (Tiny Jobs)")
    lines.append("")
    if tiny:
        for wi in tiny:
            lines.append(f"- {wi} ({weights.get(wi,1.0)}h, tasks={tasks.get(wi,0)}): {jobs[wi]['title']}")
            lines.append("  - Suggestion: consider merging with a neighboring job to reduce overhead.")
    else:
        lines.append("- (none)")
    lines.append("")

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(str(out_path))


if __name__ == "__main__":
    main()

