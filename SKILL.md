---
name: theworkshop
description: "Codex/Claude Code skill for mixed coding and non-coding work: optimized decomposition into Project->Workstreams->Jobs, repo-owned WORKFLOW.md execution contracts, success hooks with completion promises, living plan updates, lessons learned, mini dashboard, optional GitHub mirroring, and behavior-driving rewards."
---

# TheWorkshop

Use this skill in **Codex and Claude Code** to run mixed coding and non-coding projects in a structured, auditable, loopable way.

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
- **Canonical transitions**: all lifecycle state changes flow through `transition.py` (single transition engine).
- **Terminal closure modes**: projects can close as `done` or `cancelled` (both first-class).
- **Behavior-driving rewards**: jobs are not allowed to be marked `done` until reward targets are met.
- **Single-writer dashboard projection**: `dashboard_projector.py` is the control-plane writer for dashboard artifacts.
- **Mini dashboard**: keep `outputs/dashboard.html` up to date once execution begins, and **auto-open it once per session by default** (best-effort) so the user can follow along without repeated browser churn. The dashboard auto-refreshes every ~5s (pauseable).
  - Event/task logs are humanized by default for operator readability.
  - Full raw machine event payloads remain accessible from per-event details drawers.
  - `monitor_runtime.py` is the lifecycle authority for dashboard open/watch/serve/stop/cleanup.
  - Live dashboard opens reuse the existing local server URL when available instead of creating a new target per event.
  - `job_start.py --no-open` is runtime-only and does not persist `monitor_open_policy`.
  - To persist policy intentionally, pass `job_start.py --monitor-policy always|once|manual`.
  - Opt-out (tests/CI/headless): set `THEWORKSHOP_NO_OPEN=1`
  - Opt-out (no background watcher): set `THEWORKSHOP_NO_MONITOR=1`
  - Project terminal closeout prunes transient runtime artifacts while preserving canonical plans/logs/outputs.
- **Strict completion defaults for new jobs**: execution evidence and linked lessons are required unless explicit exemption reasons are recorded in job frontmatter.
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
- **Dispatch execution control plane**: orchestration output is executable, not advisory.
  - `dispatch_orchestration.py` consumes `outputs/orchestration.json`, starts runnable jobs, and emits dispatch telemetry.
  - Canonical telemetry stream: `logs/agents.jsonl` (for both manual and dispatch delegation).
  - `logs/subagent-dispatch.jsonl` remains compatibility/diagnostic telemetry for dispatch engine traces.
  - If delegation is done outside dispatch (for example direct tool-level subagents), emit lifecycle events with `agent_log.py` (`source=manual|external`) so dashboard subagent/dispatch panels stay truthful.
  - Dispatch summary: `outputs/orchestration-execution.json`
- **Repo-owned execution contract**: each project root carries a `WORKFLOW.md` file that defines polling cadence, dispatch defaults, cycle hooks, and a shared execution-policy prompt for unattended runs.
  - `workflow_check.py` validates and prints the effective contract.
  - `workflow_runner.py` runs a Symphony-style local service loop over the on-disk project graph.
- **Optional council planning mode**: run multi-planner synthesis before agreement lock.
  - `council_plan.py` uses Gemini CLI planners by default.
  - OpenAI planners are supported through `$apple-keychain` with canonical keychain service `OPENAI_KEY` injected as `OPENAI_API_KEY`.
  - Council artifacts: `outputs/council/council-plan.json`, `outputs/council/final-plan.md`
- **Schema hardening**: validate machine artifacts with shipped JSON schemas in `schemas/`.
  - `schema_validate.py` validates orchestration/truth/rewards/dashboard payloads.
  - `plan_check.py` enforces schema validity for present machine artifacts.
- **Image generation first-class**: for image jobs, run `imagegen_job.py` so key retrieval, imagegen execution, output validation, and verification logging are consistent.
  - OSS-first API env: `THEWORKSHOP_IMAGEGEN_API_KEY` (preferred and cross-platform)
  - Compatibility env aliases: `OPENAI_API_KEY`, `OPENAI_KEY` (legacy, fallback only)
  - Optional keychain mode for macOS via `$apple-keychain`: `THEWORKSHOP_IMAGEGEN_CREDENTIAL_SOURCE=keychain`
  - Opt-out (tests/headless): set `THEWORKSHOP_NO_KEYCHAIN=1`
  - Headless/no-GUI approval fallback: set `CODEX_KEYCHAIN_APPROVE=1` when keychain dialog cannot attach to a TTY/window.
- **PDF truth test portability**: `scripts/truth_gate_pdf_test.py` discovers a local Chrome/Chromium binary (via `THEWORKSHOP_PDF_BROWSER`/`THEWORKSHOP_CHROME_PATH` or system PATH) and exits with `TRUTH GATE PDF TEST SKIPPED` on unsupported platforms.
- **GitHub mirror (opt-in)**: if the project is in GitHub, offer mirroring (issues/labels/milestones + best-effort project board) and keep it synced once enabled.

## Distribution

To install/update the skill from GitHub:

```bash
git clone https://github.com/CongressionalInsights/theworkshop.git
mkdir -p "$CODEX_HOME/skills"
cp -R theworkshop "$CODEX_HOME/skills/theworkshop"
```

To update:

```bash
cd "$CODEX_HOME/skills/theworkshop" && git pull origin main
```

## Quick start (Codex runbook)

These commands are for Codex's internal runbook/audit trail. Do not present them as instructions to the user; only list them under **Commands run (audit)** after execution.

```bash
# Create a new project root
{baseDir}/scripts/project_new.py --name "My Project"

# Validate the generated execution contract
{baseDir}/scripts/workflow_check.py --project /path/to/project

# Add workstreams and jobs
{baseDir}/scripts/workstream_add.py --project /path/to/project --title "Research"
{baseDir}/scripts/job_add.py --project /path/to/project --workstream WS-... --title "Draft brief" --stakes normal
{baseDir}/scripts/job_add.py --project /path/to/project --workstream WS-... --title "Attribution sweep" --job-profile investigation_attribution
{baseDir}/scripts/job_add.py --project /path/to/project --workstream WS-... --title "Entity resolution" --job-profile identity_resolution
{baseDir}/scripts/discuss.py --project /path/to/project --work-item-id WI-... --decision "Lock key behavior" --required --no-interactive

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
{baseDir}/scripts/job_start.py --project /path/to/project --work-item-id WI-... --lessons-limit 5 --lessons-include-global
{baseDir}/scripts/job_start.py --project /path/to/project --work-item-id WI-... --monitor-policy manual
{baseDir}/scripts/verify_work.py --project /path/to/project --work-item-id WI-...
{baseDir}/scripts/job_complete.py --project /path/to/project --work-item-id WI-... --cascade
{baseDir}/scripts/workstream_complete.py --project /path/to/project --workstream-id WS-...
{baseDir}/scripts/project_complete.py --project /path/to/project

# Loop execution (planning-time opt-in)
{baseDir}/scripts/theworkshop loop --project /path/to/project --work-item-id WI-... --mode max_iterations --max-loops 3
{baseDir}/scripts/theworkshop loop --project /path/to/project --work-item-id WI-... --mode until_complete --completion-promise WI-...-DONE
{baseDir}/scripts/theworkshop loop --project /path/to/project --work-item-id WI-... --mode promise_or_max --max-loops 5 --completion-promise WI-...-DONE

# Build dashboard artifacts
{baseDir}/scripts/dashboard_projector.py --project /path/to/project

# Open dashboard (best-effort, open-once per session)
{baseDir}/scripts/dashboard_open.py --project /path/to/project

# Open + keep dashboard live (best-effort)
{baseDir}/scripts/dashboard_monitor.py --project /path/to/project

# Monitor runtime controls
{baseDir}/scripts/monitor_runtime.py start --project /path/to/project --policy once
{baseDir}/scripts/monitor_runtime.py stop --project /path/to/project

# Canonical transition engine
{baseDir}/scripts/transition.py --project /path/to/project --entity-kind job --entity-id WI-... --to-status in_progress --reason "start"
{baseDir}/scripts/project_close.py --project /path/to/project --status cancelled --reason "explicit close"

# Optional: serve dashboard over HTTP with SSE live updates
{baseDir}/scripts/dashboard_server.py --project /path/to/project --open

# Orchestration dispatch (delegated execution)
{baseDir}/scripts/dispatch_orchestration.py --project /path/to/project
{baseDir}/scripts/dispatch_orchestration.py --project /path/to/project --dry-run

# Symphony-style local runner over WORKFLOW.md + project graph
{baseDir}/scripts/workflow_runner.py --project /path/to/project --once
{baseDir}/scripts/workflow_runner.py --project /path/to/project --detach

# Optional council planning before agreement lock
{baseDir}/scripts/council_plan.py --project /path/to/project --dry-run

# Validate machine artifacts against JSON schemas
{baseDir}/scripts/schema_validate.py --project /path/to/project

# Lessons operations
{baseDir}/scripts/lessons_query.py --project /path/to/project --query "evidence attribution" --linked WI-... --include-global
{baseDir}/scripts/lessons_apply.py --project /path/to/project --work-item-id WI-... --limit 5

# Run image generation for a WI
{baseDir}/scripts/imagegen_job.py --project /path/to/project --work-item-id WI-...

# Reliability preflight
{baseDir}/scripts/doctor.py
{baseDir}/scripts/health.py --project /path/to/project --repair

# Quick ad-hoc lane (separate from workstream/job graph)
{baseDir}/scripts/quick.py --project /path/to/project --title "One-off task" --command "echo done"

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
