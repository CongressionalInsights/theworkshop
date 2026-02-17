#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from twlib import list_job_dirs, list_workstream_dirs, normalize_str_list, now_iso, read_md, resolve_project_root


RUNNABLE_STATUSES = {"planned", "blocked", "in_progress"}


@dataclass
class JobNode:
    work_item_id: str
    title: str
    status: str
    estimate_hours: float
    depends_on: list[str]
    plan_path: str


def parse_estimate_hours(value: object) -> float:
    try:
        estimate = float(value or 1.0)
    except Exception:
        estimate = 1.0
    if estimate <= 0:
        return 1.0
    return estimate


def parse_positive_int(value: object, default: int) -> int:
    try:
        parsed = int(str(value).strip())
    except Exception:
        return default
    if parsed <= 0:
        return default
    return parsed


def scan_jobs(project_root: Path) -> dict[str, JobNode]:
    out: dict[str, JobNode] = {}
    for ws_dir in list_workstream_dirs(project_root):
        for job_dir in list_job_dirs(ws_dir):
            plan_path = job_dir / "plan.md"
            doc = read_md(plan_path)
            fm = doc.frontmatter
            wi = str(fm.get("work_item_id") or "").strip()
            if not wi:
                continue
            if wi in out:
                continue
            out[wi] = JobNode(
                work_item_id=wi,
                title=str(fm.get("title") or "").strip(),
                status=str(fm.get("status") or "planned").strip(),
                estimate_hours=parse_estimate_hours(fm.get("estimate_hours")),
                depends_on=normalize_str_list(fm.get("depends_on")),
                plan_path=str(plan_path.relative_to(project_root)),
            )
    return out


def critical_path(
    node_ids: list[str],
    edges: list[tuple[str, str]],
    weights: dict[str, float],
) -> tuple[list[str], float, bool]:
    indeg = {n: 0 for n in node_ids}
    preds: dict[str, list[str]] = defaultdict(list)
    adj: dict[str, list[str]] = defaultdict(list)
    for src, dst in edges:
        if src not in indeg or dst not in indeg:
            continue
        indeg[dst] += 1
        adj[src].append(dst)
        preds[dst].append(src)

    frontier = sorted([n for n in node_ids if indeg[n] == 0])
    topo_order: list[str] = []
    while frontier:
        cur = frontier.pop(0)
        topo_order.append(cur)
        for child in sorted(adj.get(cur, [])):
            indeg[child] -= 1
            if indeg[child] == 0:
                frontier.append(child)
        frontier = sorted(frontier)

    if len(topo_order) != len(node_ids):
        return [], 0.0, False

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

    if not dist:
        return [], 0.0, True

    end = max(dist.keys(), key=lambda wi: dist[wi])
    total = dist[end]
    path: list[str] = []
    cur: str | None = end
    while cur:
        path.append(cur)
        cur = parent.get(cur)
    path.reverse()
    return path, total, True


def policy_parallel_limit(policy: str, configured_limit: int) -> int:
    # Keep policy handling conservative: when explicitly serial/off/manual, force single-agent waves.
    if policy in {"serial", "single", "manual", "off", "disabled", "none"}:
        return 1
    return configured_limit


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute deterministic parallel orchestration waves for runnable TheWorkshop jobs.")
    parser.add_argument("--project", help="Project root (defaults to nearest parent with plan.md)")
    parser.add_argument("--out", help="Output JSON path (default: outputs/orchestration.json)")
    args = parser.parse_args()

    project_root = resolve_project_root(args.project)
    out_dir = project_root / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out).expanduser().resolve() if args.out else out_dir / "orchestration.json"

    project_doc = read_md(project_root / "plan.md")
    project_fm = project_doc.frontmatter
    subagent_policy = str(project_fm.get("subagent_policy") or "auto").strip().lower() or "auto"
    env_policy = str(os.environ.get("THEWORKSHOP_SUBAGENT_POLICY") or "").strip().lower()
    if env_policy:
        subagent_policy = env_policy
    if str(os.environ.get("THEWORKSHOP_NO_SUBAGENTS") or "").strip() == "1":
        subagent_policy = "off"

    configured_limit = parse_positive_int(project_fm.get("max_parallel_agents"), 3)
    env_limit_raw = os.environ.get("THEWORKSHOP_MAX_PARALLEL_AGENTS")
    if env_limit_raw is not None:
        configured_limit = parse_positive_int(env_limit_raw, configured_limit)
    effective_limit = policy_parallel_limit(subagent_policy, configured_limit)

    jobs = scan_jobs(project_root)
    node_ids = sorted(jobs.keys())

    # Full-project critical path for planning visibility.
    all_edges: list[tuple[str, str]] = []
    for wi in node_ids:
        for dep in jobs[wi].depends_on:
            dep_id = dep.strip()
            if dep_id in jobs:
                all_edges.append((dep_id, wi))
    all_edges = sorted(set(all_edges))
    weights = {wi: jobs[wi].estimate_hours for wi in node_ids}
    cp_nodes, cp_hours, cp_available = critical_path(node_ids, all_edges, weights)

    active_ids = sorted([wi for wi in node_ids if jobs[wi].status in RUNNABLE_STATUSES])
    active_set = set(active_ids)

    indeg: dict[str, int] = {wi: 0 for wi in active_ids}
    adj: dict[str, list[str]] = defaultdict(list)
    blocked_reasons: dict[str, dict[str, list[str]]] = {
        wi: {"missing_dependencies": [], "not_done_dependencies": []} for wi in active_ids
    }

    for wi in active_ids:
        for dep in jobs[wi].depends_on:
            dep_id = dep.strip()
            if not dep_id:
                continue
            dep_node = jobs.get(dep_id)
            if dep_node is None:
                blocked_reasons[wi]["missing_dependencies"].append(dep_id)
                continue
            if dep_node.status == "done":
                continue
            if dep_id in active_set:
                indeg[wi] += 1
                adj[dep_id].append(wi)
                continue
            blocked_reasons[wi]["not_done_dependencies"].append(dep_id)

    for dep_id in adj:
        adj[dep_id] = sorted(set(adj[dep_id]))
    for wi in blocked_reasons:
        blocked_reasons[wi]["missing_dependencies"] = sorted(set(blocked_reasons[wi]["missing_dependencies"]))
        blocked_reasons[wi]["not_done_dependencies"] = sorted(set(blocked_reasons[wi]["not_done_dependencies"]))

    frontier = sorted(
        [
            wi
            for wi in active_ids
            if indeg[wi] == 0
            and not blocked_reasons[wi]["missing_dependencies"]
            and not blocked_reasons[wi]["not_done_dependencies"]
        ]
    )
    waves: list[list[str]] = []
    scheduled: set[str] = set()

    while frontier:
        current_wave = frontier[:effective_limit]
        waves.append(current_wave)
        frontier = frontier[effective_limit:]
        for wi in current_wave:
            scheduled.add(wi)
            for child in adj.get(wi, []):
                indeg[child] -= 1
                if indeg[child] == 0:
                    blockers = blocked_reasons[child]
                    if not blockers["missing_dependencies"] and not blockers["not_done_dependencies"]:
                        frontier.append(child)
        frontier = sorted(set(frontier))

    blocked_jobs = []
    for wi in active_ids:
        if wi in scheduled:
            continue
        blockers = blocked_reasons[wi]
        if blockers["missing_dependencies"] or blockers["not_done_dependencies"] or indeg[wi] > 0:
            dep_cycle_or_pending = []
            if indeg[wi] > 0:
                dep_cycle_or_pending = sorted(
                    [dep for dep in jobs[wi].depends_on if dep in active_set and dep not in scheduled]
                )
            blocked_jobs.append(
                {
                    "work_item_id": wi,
                    "status": jobs[wi].status,
                    "missing_dependencies": blockers["missing_dependencies"],
                    "not_done_dependencies": blockers["not_done_dependencies"],
                    "pending_or_cyclic_dependencies": dep_cycle_or_pending,
                }
            )
    blocked_jobs = sorted(blocked_jobs, key=lambda item: item["work_item_id"])
    stale_dependency_count = 0
    inv_path = project_root / "outputs" / "invalidation-report.json"
    if inv_path.exists():
        try:
            inv = json.loads(inv_path.read_text(encoding="utf-8"))
            counts = inv.get("counts") if isinstance(inv, dict) else {}
            if isinstance(counts, dict):
                stale_dependency_count = int(counts.get("stale_jobs") or 0)
        except Exception:
            stale_dependency_count = 0

    runnable_now = waves[0] if waves else []
    wave_objects = [{"wave_index": idx + 1, "work_items": wave} for idx, wave in enumerate(waves)]

    payload = {
        "schema": "theworkshop.orchestration.v1",
        "generated_at": now_iso(),
        "project": str(project_root),
        "subagent_policy": subagent_policy,
        "subagent_policy_env_override": env_policy,
        "subagents_disabled_env": str(os.environ.get("THEWORKSHOP_NO_SUBAGENTS") or "").strip() == "1",
        "max_parallel_agents": {
            "configured": configured_limit,
            "effective": effective_limit,
            "env_override": env_limit_raw if env_limit_raw is not None else "",
        },
        "runnable_statuses": sorted(RUNNABLE_STATUSES),
        "critical_path": {
            "work_items": cp_nodes,
            "total_estimate_hours": round(cp_hours, 6),
            "available": cp_available,
        },
        "counts": {
            "all_jobs": len(node_ids),
            "active_jobs": len(active_ids),
            "scheduled_jobs": len(scheduled),
            "blocked_jobs": len(blocked_jobs),
            "wave_count": len(waves),
        },
        "runnable_now": runnable_now,
        # Keep both keys for compatibility with older/newer readers.
        "parallel_groups": waves,
        "groups": waves,
        "group_details": wave_objects,
        "critical_path_hours": round(cp_hours, 6),
        "blocked_jobs": blocked_jobs,
        "stale_dependency_count": stale_dependency_count,
    }

    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(str(out_path))


if __name__ == "__main__":
    main()
