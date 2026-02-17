# TheWorkshop Workflow

## Overview

TheWorkshop runs in two stages:

1. **Plan (agree first)**: intake -> decomposition -> optimization -> success hooks -> explicit agreement.
2. **Execute (loopable)**: run jobs sequentially (or in safe parallel) with reward gating and continuous plan updates.

## Stage 1: Plan (Agree First)

### Step 1: Intake

Collect:
- Goal + audience
- Deliverables (exact files, formats)
- Constraints (deadline, quality bar, tools, integrations)
- Tradeoffs (speed vs polish vs depth)

### Step 2: Decompose

Propose:
- Workstreams (2-6 typically)
- Jobs per workstream (smallest verifiable units)
- Dependencies (`depends_on`)
- Optional waves (timeboxes) if useful

### Step 3: Optimize (mandatory)

Deterministic heuristics to apply:
- Split jobs until each has a single dominant deliverable and clear verification.
- Merge tiny jobs that add overhead without improving verifiability.
- Minimize dependencies; maximize safe parallel groups.
- Identify critical path (weighted by `estimate_hours`).
- Rewrite ambiguous acceptance criteria into checkable outcomes and explicit output paths.

### Step 4: Success Hooks

For project/workstream/job:
- Acceptance Criteria
- Verification (how we'll prove it)
- Completion promise `<promise>{ID}-DONE</promise>`

### Step 5: Agreement Gate

Before execution begins, record agreement in project `plan.md`:
- `agreement_status: agreed`
- `agreed_at: <timestamp>`
- `agreed_notes: <short>`

## Stage 2: Execute (Loopable)

### Plan-as-control-plane updates (required)

On job state transitions, update:
- YAML frontmatter fields: `status`, `started_at`, `completed_at`, `updated_at`
- `# Progress Log` (append-only)
- Workstream job table (if present)
- Project workstream summary (if present)

Status fields are not manual-only: run `theworkshop rollup --project <path>` (or `plan_sync.py`) so parent statuses are derived from child state deterministically:
- Workstream status from jobs:
  - any `in_progress` => `in_progress`
  - else any `blocked` => `blocked`
  - else all `{done,cancelled}` => `done`
  - else `planned`
- Project status from workstreams uses the same precedence.

### Reward gating (required)

After each job iteration:
1. Run `plan_check.py`
2. Run `reward_eval.py` (updates `reward_last_*`)
3. If reward < target: take the top next-action hint and iterate
4. Only mark job `done` and emit `<promise>WI-...-DONE</promise>` when:
   - verification evidence exists, and
   - `reward_last_score >= reward_target`

### TruthGate (required)

Before claiming a job passed verification, run TruthGate checks and persist results on the job plan frontmatter:
- `truth_last_status`: `pass`, `fail`, or `unknown`
- `truth_last_failures`: list of the latest failed checks/messages
- `truth_last_checked_at`: timestamp of the latest TruthGate run

TruthGate must be current with the latest job artifacts. If TruthGate fails, the job remains `in_progress` (or `blocked`) until failures are resolved.

### Orchestration + agent log flow (required when delegation is enabled)

When the execution loop can run independent jobs in parallel:
1. Run `orchestrate_plan.py` to produce `outputs/orchestration.json` with deterministic parallel groups and critical path.
2. If 2 or more runnable independent jobs exist and `subagent_policy != off`, delegate execution to sub-agents (respecting max parallel limits).
3. Append sub-agent lifecycle events to `logs/agents.jsonl` (`active`, `completed`, `failed` states).
4. Rebuild dashboard artifacts so orchestration and sub-agent telemetry stays visible.

### Dashboard updates (required)

Regenerate:
- `outputs/dashboard.json`
- `outputs/dashboard.md`
- `outputs/dashboard.html`

Triggers:
- at execution start
- on any job status change
- after each reward eval
- at closeout

At execution start (and after completion as needed), TheWorkshop must also **auto-open** the dashboard in a new browser window (best-effort, open-once per session) so the user can follow progress.
- The HTML auto-refreshes every ~5s by default and can be paused in-page.
- Opt-out (tests/CI/headless): set `THEWORKSHOP_NO_OPEN=1`.
- TheWorkshop also starts a best-effort background watcher (`dashboard_watch.py`) so the dashboard artifacts keep updating even when no explicit dashboard rebuild trigger fires (opt-out: `THEWORKSHOP_NO_MONITOR=1`).

### Usage + spend telemetry (required)

When rebuilding dashboard/usage artifacts:
- Always include token telemetry source and confidence.
- Prefer exact session USD from CodexBar when available.
- Otherwise estimate session/project USD from token usage + `references/token-rates.json`.
- Resolve billing mode and display billed vs API-equivalent values:
  - `subscription_auth`: billed session/project cost is `$0` (subscription-included), API-equivalent estimates remain visible for optimization.
  - `metered_api`: billed values use exact metered data when available.
  - `unknown`: estimate-first behavior with low-confidence billing labels.
- Support project-local overrides via `notes/token-rates.override.json` (invalid override is ignored with warning).
- Optional deterministic billing override: `THEWORKSHOP_BILLING_MODE=subscription_auth|metered_api|unknown`.
- Allocate project delta spend by work item from `logs/execution.jsonl` weights:
  - `weight = max(1, duration_sec) + 0.5`
  - rows with no `work_item_id` roll into unattributed spend.

### Image generation jobs (required pattern)

For jobs that generate visual assets:
- Use `theworkshop imagegen-job --project <path> --work-item-id WI-...`
- This runner uses:
  - Keychain service `OPENAI_KEY` (fallback `OPENAI_API_KEY`)
  - Injected env `OPENAI_API_KEY` for imagegen compatibility
  - Batch prompts from `artifacts/prompts.jsonl`
  - Output validation + verification logging
- Headless/test opt-out for keychain: `THEWORKSHOP_NO_KEYCHAIN=1`
- If Keychain approval dialog cannot attach to GUI/TTY, use explicit non-interactive approval:
  - `CODEX_KEYCHAIN_APPROVE=1`
  - This variable is interpreted by the external `$apple-keychain` skill runner used by `imagegen_job.py`.

### GitHub mirror (opt-in)

If GitHub is detected or provided, offer mirroring. Do not create external artifacts until enabled.

Once enabled, keep `notes/github-map.json` and issue/milestone status synced.
