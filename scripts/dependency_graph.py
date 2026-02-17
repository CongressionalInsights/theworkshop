#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from twlib import list_job_dirs, list_workstream_dirs, normalize_str_list, now_iso, read_md, resolve_project_root


@dataclass
class JobNode:
    work_item_id: str
    title: str
    status: str
    estimate_hours: float
    depends_on: list[str]
    workstream_id: str
    workstream_title: str
    plan_path: str


def parse_estimate_hours(value: object) -> float:
    try:
        estimate = float(value or 1.0)
    except Exception:
        estimate = 1.0
    if estimate <= 0:
        return 1.0
    return estimate


def fallback_workstream_id(ws_dir: Path) -> str:
    parts = ws_dir.name.split("-", 3)
    if len(parts) >= 3:
        return "-".join(parts[:3])
    return ws_dir.name


def scan_jobs(project_root: Path) -> tuple[dict[str, JobNode], list[dict[str, str]]]:
    nodes: dict[str, JobNode] = {}
    duplicates: list[dict[str, str]] = []
    for ws_dir in list_workstream_dirs(project_root):
        ws_doc = read_md(ws_dir / "plan.md")
        ws_fm = ws_doc.frontmatter
        ws_id = str(ws_fm.get("id") or "").strip() or fallback_workstream_id(ws_dir)
        ws_title = str(ws_fm.get("title") or ws_dir.name).strip()

        for job_dir in list_job_dirs(ws_dir):
            doc = read_md(job_dir / "plan.md")
            fm = doc.frontmatter
            wi = str(fm.get("work_item_id") or "").strip()
            if not wi:
                continue
            node = JobNode(
                work_item_id=wi,
                title=str(fm.get("title") or "").strip(),
                status=str(fm.get("status") or "planned").strip(),
                estimate_hours=parse_estimate_hours(fm.get("estimate_hours")),
                depends_on=normalize_str_list(fm.get("depends_on")),
                workstream_id=ws_id,
                workstream_title=ws_title,
                plan_path=str((job_dir / "plan.md").relative_to(project_root)),
            )
            if wi in nodes:
                duplicates.append(
                    {
                        "work_item_id": wi,
                        "existing_plan_path": nodes[wi].plan_path,
                        "duplicate_plan_path": node.plan_path,
                    }
                )
                continue
            nodes[wi] = node
    return nodes, duplicates


def build_graph(
    nodes: dict[str, JobNode],
) -> tuple[list[tuple[str, str]], dict[str, list[str]], list[dict[str, str]]]:
    edges: list[tuple[str, str]] = []
    reverse_deps: dict[str, list[str]] = {wi: [] for wi in nodes}
    missing_dependencies: list[dict[str, str]] = []

    for wi in sorted(nodes.keys()):
        node = nodes[wi]
        for dep in node.depends_on:
            dep_id = dep.strip()
            if not dep_id:
                continue
            if dep_id not in nodes:
                missing_dependencies.append({"work_item_id": wi, "depends_on": dep_id})
                continue
            edges.append((dep_id, wi))
            reverse_deps[dep_id].append(wi)

    edges = sorted(set(edges))
    for dep_id in reverse_deps:
        reverse_deps[dep_id] = sorted(set(reverse_deps[dep_id]))

    return edges, reverse_deps, missing_dependencies


def topo_groups(nodes: list[str], edges: list[tuple[str, str]]) -> tuple[list[list[str]], list[str], list[str]]:
    indeg = {n: 0 for n in nodes}
    adj: dict[str, list[str]] = defaultdict(list)
    preds: dict[str, list[str]] = defaultdict(list)

    for src, dst in edges:
        if src not in indeg or dst not in indeg:
            continue
        adj[src].append(dst)
        preds[dst].append(src)
        indeg[dst] += 1

    for src in adj:
        adj[src] = sorted(set(adj[src]))
    for dst in preds:
        preds[dst] = sorted(set(preds[dst]))

    groups: list[list[str]] = []
    processed: list[str] = []
    frontier = sorted([n for n in nodes if indeg[n] == 0])

    while frontier:
        group = list(frontier)
        groups.append(group)
        next_frontier: list[str] = []
        for node in group:
            processed.append(node)
            for child in adj.get(node, []):
                indeg[child] -= 1
                if indeg[child] == 0:
                    next_frontier.append(child)
        frontier = sorted(set(next_frontier))

    cycle_nodes = sorted([n for n in nodes if n not in set(processed)])
    return groups, processed, cycle_nodes


def critical_path(
    topo_order: list[str],
    edges: list[tuple[str, str]],
    weights: dict[str, float],
) -> tuple[list[str], float]:
    if not topo_order:
        return [], 0.0

    preds: dict[str, list[str]] = defaultdict(list)
    for src, dst in edges:
        preds[dst].append(src)

    dist: dict[str, float] = {}
    parent: dict[str, str | None] = {}
    for node in topo_order:
        node_weight = weights.get(node, 1.0)
        best = node_weight
        best_parent: str | None = None
        for pred in preds.get(node, []):
            if pred not in dist:
                continue
            cand = dist[pred] + node_weight
            if cand > best:
                best = cand
                best_parent = pred
        dist[node] = best
        parent[node] = best_parent

    end = max(dist.keys(), key=lambda wi: dist[wi])
    total = dist[end]
    path: list[str] = []
    cur: str | None = end
    while cur:
        path.append(cur)
        cur = parent.get(cur)
    path.reverse()
    return path, total


def main() -> None:
    parser = argparse.ArgumentParser(description="Build job dependency DAG and critical path for a TheWorkshop project.")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--out", help="Output JSON path (default: outputs/dependency-graph.json)")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    out_dir = project_root / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out).expanduser().resolve() if args.out else out_dir / "dependency-graph.json"

    nodes_by_id, duplicates = scan_jobs(project_root)
    node_ids = sorted(nodes_by_id.keys())
    edges, reverse_deps, missing_dependencies = build_graph(nodes_by_id)
    groups, topo_order, cycle_nodes = topo_groups(node_ids, edges)

    weights = {wi: nodes_by_id[wi].estimate_hours for wi in node_ids}
    cp_nodes, cp_hours = ([], 0.0)
    if not cycle_nodes:
        cp_nodes, cp_hours = critical_path(topo_order, edges, weights)

    payload = {
        "schema": "theworkshop.dependencygraph.v1",
        "generated_at": now_iso(),
        "project": str(project_root),
        "job_count": len(node_ids),
        "edge_count": len(edges),
        "nodes": [
            {
                "work_item_id": wi,
                "title": nodes_by_id[wi].title,
                "status": nodes_by_id[wi].status,
                "estimate_hours": nodes_by_id[wi].estimate_hours,
                "depends_on": nodes_by_id[wi].depends_on,
                "workstream_id": nodes_by_id[wi].workstream_id,
                "workstream_title": nodes_by_id[wi].workstream_title,
                "plan_path": nodes_by_id[wi].plan_path,
            }
            for wi in node_ids
        ],
        "edges": [{"from": src, "to": dst} for src, dst in edges],
        "reverse_deps": {wi: reverse_deps.get(wi, []) for wi in node_ids},
        "topo_groups": groups,
        "critical_path": {
            "work_items": cp_nodes,
            "total_estimate_hours": round(cp_hours, 6),
            "available": not cycle_nodes,
        },
        "diagnostics": {
            "missing_dependencies": missing_dependencies,
            "cycle_nodes": cycle_nodes,
            "duplicate_work_item_ids": duplicates,
        },
    }

    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(str(out_path))


if __name__ == "__main__":
    main()
