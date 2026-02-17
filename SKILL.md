---
name: theworkshop
description: "Project OS for non-coding work: optimized decomposition into Project->Workstreams->Jobs, success hooks with completion promises, living plan updates, lessons learned, mini dashboard, optional GitHub mirroring, and behavior-driving rewards."
---

# TheWorkshop

Use this skill to run **non-coding projects** in a structured, auditable, loopable way.

TheWorkshop is **operatorless**: the user does not run terminal commands. Codex executes scripts directly and only asks the user for **click-only** permissions when required (auth, keychain, etc.).

## Core principles (non-negotiable)

- **Project-first**: the project is the primary unit.
- **Optimized decomposition**: before execution, decompose and *optimize* structure, order, timing, and dependencies.
- **Agreement gate**: user and agent agree on the Project/Workstreams/Jobs and success hooks before executing.
- **Success hooks everywhere**: Project/Workstream/Job each has:
  - Acceptance Criteria
  - Verification
  - Completion promise: `<promise>{ID}-DONE</promise>` (only emit when objectively true)
- **Living plans**: plans are updated as the agent works (status, timestamps, progress log).
- **Behavior-driving rewards**: jobs are not allowed to be marked `done` until reward targets are met.
- **Mini dashboard**: keep `outputs/dashboard.html` up to date once execution begins, and **auto-open it in a new browser window** (best-effort) so the user can follow along. The dashboard auto-refreshes every ~5s (pauseable).
  - Opt-out (tests/CI/headless): set `THEWORKSHOP_NO_OPEN=1`
  - Opt-out (no background watcher): set `THEWORKSHOP_NO_MONITOR=1`
- **Spend visibility**: dashboard/usage always include token telemetry and cost source metadata.
  - If CodexBar provides cost, treat as exact (`cost_source=codexbar_exact`, high confidence).
  - Otherwise estimate from session-token usage using `references/token-rates.json` (`cost_source=estimated_from_rates`).
  - Billing mode is resolved as `subscription_auth|metered_api|unknown`:
    - `subscription_auth`: display billed costs as `$0` (subscription-included) with API-equivalent secondary estimates.
    - `metered_api`: display billed costs from exact CodexBar data when available.
    - `unknown`: fallback to estimate-first display with low-confidence billing labels.
  - Optional billing override for deterministic testing/ops: `THEWORKSHOP_BILLING_MODE=subscription_auth|metered_api|unknown`.
  - Optional per-project rate override: `notes/token-rates.override.json`.
  - Per-work-item spend is allocation-based from execution logs and is approximate (not invoice truth).
- **Delegation policy**: when 2 or more independent runnable jobs exist and `subagent_policy != off`, delegation is required.
  - `THEWORKSHOP_SUBAGENT_POLICY`: override policy (`auto`, `on`, or `off`)
  - `THEWORKSHOP_MAX_PARALLEL_AGENTS`: cap concurrent delegated agents
  - `THEWORKSHOP_NO_SUBAGENTS=1`: hard-disable delegation for tests/headless runs
- **Image generation first-class**: for image jobs, run `imagegen_job.py` so key retrieval, imagegen execution, output validation, and verification logging are consistent.
  - Canonical Keychain service: `OPENAI_KEY`
  - Compatibility env injected for imagegen: `OPENAI_API_KEY`
  - Opt-out (tests/headless): set `THEWORKSHOP_NO_KEYCHAIN=1`
  - Headless/no-GUI approval fallback: set `CODEX_KEYCHAIN_APPROVE=1` when Keychain dialog cannot attach to a TTY/window (handled by the external `$apple-keychain` runner).
- **GitHub mirror (opt-in)**: if the project is in GitHub, offer mirroring (issues/labels/milestones + best-effort project board) and keep it synced once enabled.

## Quick start (Codex runbook)

These commands are for Codex's internal runbook/audit trail. Do not present them as instructions to the user; only list them under **Commands run (audit)** after execution.

```bash
# Create a new project root
{baseDir}/scripts/project_new.py --name "My Project"

# Add workstreams and jobs
{baseDir}/scripts/workstream_add.py --project /path/to/project --title "Research"
{baseDir}/scripts/job_add.py --project /path/to/project --workstream WS-... --title "Draft brief" --stakes normal

# Build/update the task tracker (1 row per job)
{baseDir}/scripts/task_tracker_build.py --project /path/to/project

# Keep plan tables (project/workstream marker blocks) in sync
{baseDir}/scripts/plan_sync.py --project /path/to/project

# Explicit status rollup + sync
{baseDir}/scripts/theworkshop rollup --project /path/to/project

# Validate plans and gates
{baseDir}/scripts/plan_check.py --project /path/to/project

# Compute reward scores + next actions (updates job plan frontmatter)
{baseDir}/scripts/reward_eval.py --project /path/to/project

# Lifecycle helpers (reward-gated completion)
{baseDir}/scripts/job_start.py --project /path/to/project --work-item-id WI-...
{baseDir}/scripts/job_complete.py --project /path/to/project --work-item-id WI-... --cascade
{baseDir}/scripts/workstream_complete.py --project /path/to/project --workstream-id WS-...
{baseDir}/scripts/project_complete.py --project /path/to/project

# Build dashboard artifacts
{baseDir}/scripts/dashboard_build.py --project /path/to/project

# Open dashboard (best-effort, open-once per session)
{baseDir}/scripts/dashboard_open.py --project /path/to/project

# Open + keep dashboard live (best-effort)
{baseDir}/scripts/dashboard_monitor.py --project /path/to/project

# Run image generation for a WI (imagegen + apple-keychain)
{baseDir}/scripts/imagegen_job.py --project /path/to/project --work-item-id WI-...

# Reliability preflight
{baseDir}/scripts/doctor.py

# Usage snapshot (tokens + spend metadata)
{baseDir}/scripts/usage_snapshot.py --project /path/to/project
```

## User-facing response template (default)

1. Status / what I'm doing
2. Action required (click-only) (only if needed)
3. Outputs (paths produced/updated)
4. Commands run (audit)

## References

Read these first when operating the skill:
- `references/workflow.md`
- `references/prompting.md`
- `references/templates.md`
- `references/rewards.md`
