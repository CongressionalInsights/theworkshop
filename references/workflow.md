# TheWorkshop Workflow

## Overview

This repo is the **public OSS baseline** for TheWorkshop.

- The public contract covers the portable local framework plus optional adapters.
- Private/custom operator overlays are separate and are not standardized here.
- Adapter-backed capabilities should fail only when explicitly selected.

TheWorkshop runs in two stages:

1. **Plan (agree first)**: intake -> decomposition -> optimization -> success hooks -> explicit agreement.
2. **Execute (loopable)**: run jobs sequentially (or in safe parallel) with reward gating and continuous plan updates.

## Repo-owned `WORKFLOW.md` contract

Each TheWorkshop project root now includes a `WORKFLOW.md` file. It is the local execution contract
for unattended runs and plays the same role that repo-owned workflow files play in service-style
orchestrators:

- frontmatter defines runtime defaults:
  - `work_source.kind` (currently `local_project`)
  - `polling.interval_sec`
  - `orchestration.auto_refresh`
  - `validation.require_agreement`
  - `validation.run_plan_check`
  - `dispatch.runner`, `dispatch.max_parallel`, `dispatch.timeout_sec`
  - `dispatch.continue_on_error`, `dispatch.no_complete`, `dispatch.no_monitor`
  - `dispatch.open_policy`, `dispatch.codex_args`
  - `hooks.before_cycle`, `hooks.after_cycle`, `hooks.timeout_sec`
- markdown body is a shared execution-policy prompt prepended to delegated work-item prompts

Operational commands:

- `theworkshop workflow-check --project <path>` validates and prints the effective contract
- `theworkshop serve --project <path> --once` runs one unattended cycle
- `theworkshop serve --project <path> --detach` runs a background service loop

Runner behavior:

- reloads `WORKFLOW.md` at the start of each cycle
- respects project agreement gating before dispatch
- optionally refreshes orchestration artifacts before dispatch
- dispatches runnable jobs from the on-disk project graph
- emits runner telemetry to `logs/workflow-runner.jsonl`
- writes live state to `tmp/workflow-runner.json`

## Optional Adapters

The portable/core workflow path does not require every integration shipped in the repo.

Optional adapters include:
- Codex telemetry / CodexBar spend
- Gemini / OpenAI council planners
- Apple Keychain credential path
- imagegen skill bridge
- GitHub mirroring

Use `python3 scripts/doctor.py --profile codex` for the Codex-first path and
`python3 scripts/doctor.py --profile portable` for the portable public baseline.

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
- Choose `job_add --job-profile` deliberately:
  - `investigation_attribution` for property/attribution sweeps
  - `identity_resolution` for same-entity determinations
  - `default` for general jobs
- For investigative work, acceptance criteria must explicitly separate attributable matches from collisions.

### Step 4: Intent Lock (`theworkshop discuss`)

Before execution for ambiguous jobs/workstreams, capture context in:
- `notes/context/<WS-or-WI>-CONTEXT.md`

The context file should record:
- `locked_decisions` (what is in-scope and fixed)
- `deferred_ideas` (explicitly out-of-scope for now)
- `notes` (non-decision context)

For jobs that require pre-execution alignment, set:
- `context_required: true`
- `context_ref: notes/context/WI-...-CONTEXT.md`

Execution gate behavior:
- `job_start` fails if `context_required=true` and `context_ref` is missing/empty.
- `plan_check` enforces the same requirement when execution is in progress/done.

### Step 5: Success Hooks

For project/workstream/job:
- Acceptance Criteria
- Verification (how we'll prove it)
- Completion promise `<promise>{ID}-DONE</promise>`

### Step 6: Looping decision (plan-time)

Before execution enters the run phase, decide whether the WI should be looped:

- Should loop mode be enabled for this WI?
- Loop mode:
  - `until_complete` = continue until completion criteria are observed
  - `max_iterations` = run a bounded number of attempts
  - `promise_or_max` = stop when either promise is seen or max iterations reached
- `max_iterations`:
  - if not set on the WI frontmatter, default from `stakes` (`low=2`, `normal=3`, `high=5`, `critical=7`)
  - can be explicitly overridden in planning (`loop_max_iterations`)
- completion promise only required for `until_complete`/`promise_or_max` when running unbounded or if no finite cap exists

Record the decision in the project-level `# Decisions` section and on the job frontmatter using:

- `loop_enabled`
- `loop_mode`
- `loop_max_iterations`
- `loop_target_promise`

If looping is planned as the main execution path, call:

- `theworkshop loop --project <path> --work-item-id WI-... --mode ... [--max-loops ...] [--completion-promise ...]`

### Step 7: Agreement Gate

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
- `cancelled` is terminal and explicit; rollups do not auto-overwrite cancelled entities.

Plan quality checks:
- `plan_check.py` emits warnings for weak/placeholder job content while status is `planned`.
- `plan_check.py` hard-fails weak/placeholder content for jobs in `in_progress` or `done`.

### Canonical transition engine (required)

Use `transition.py` as the lifecycle authority for status changes:
- `project|workstream|job` transitions
- timestamp updates (`started_at`, `completed_at`, `cancelled_at`, `updated_at`)
- progress-log append with transition id and reason
- transition event append to `logs/events.jsonl`
- project-level `last_transition_id` update

Aliases (`job_start.py`, `job_complete.py`, `workstream_complete.py`, `project_complete.py`, `project_close.py`) are wrappers over the same transition path.

### Lessons application at start (required default)

`job_start.py` auto-applies ranked lessons into `# Relevant Lessons Learned` before transitioning to `in_progress`.

Controls:
- `--no-apply-lessons`
- `--lessons-limit N`
- `--lessons-include-global`
- `--monitor-policy always|once|manual` (persistent monitor policy override)

Default merge policy:
- Replace placeholder lesson sections.
- Append non-duplicate lessons for already-populated sections.

### Reward gating (required)

After each job iteration:
1. Run `plan_check.py`
2. Run `reward_eval.py` (updates `reward_last_*`)
3. If reward < target: take the top next-action hint and iterate
4. Only mark job `done` and emit `<promise>WI-...-DONE</promise>` when:
   - verification evidence exists, and
   - `reward_last_score >= reward_target`

Content-quality interaction:
- reward scoring penalizes placeholder/boilerplate sections and weak specificity.
- next-action hints prioritize objective/acceptance/verification rewrites when quality is low.

### TruthGate (required)

Before claiming a job passed verification, run TruthGate checks and persist results on the job plan frontmatter:
- `truth_last_status`: `pass`, `fail`, or `unknown`
- `truth_last_failures`: list of the latest failed checks/messages
- `truth_last_checked_at`: timestamp of the latest TruthGate run

TruthGate must be current with the latest job artifacts. If TruthGate fails, the job remains `in_progress` (or `blocked`) until failures are resolved.

Strict defaults for newly created jobs:
- execution evidence is required (`execution_log_required: true`) unless `execution_log_exemption_reason` is set.
- linked lesson capture is required (`lesson_capture_required: true`) unless `lesson_capture_exemption_reason` is set.
- Truth checks enforce these requirements with `work_item_execution_logged` and `linked_lesson_captured`.

### Verify Work / UAT (recommended)

Use `theworkshop verify-work` to run resumable conversational UAT over observable acceptance criteria.

Artifacts:
- `outputs/uat/<run-id>-UAT.json`
- `outputs/uat/<run-id>-UAT.md`

Job frontmatter fields updated by verify-work:
- `uat_last_status`
- `uat_last_checked_at`
- `uat_open_issues`
- `uat_follow_up_actions`

Gate interaction:
- `reward_eval.py` uses unresolved UAT issues to lower reward score and drive next-action hints.
- `job_complete.py` blocks completion when unresolved UAT issues exist.

### Orchestration + agent log flow (required when delegation is enabled)

When the execution loop can run independent jobs in parallel:
1. Run `orchestrate_plan.py` to produce `outputs/orchestration.json` with deterministic parallel groups and critical path.
2. If 2 or more runnable independent jobs exist and `subagent_policy != off`, run `dispatch_orchestration.py` to execute runnable groups (respecting max parallel limits).
3. Delegation telemetry contract:
   - Canonical stream for all delegation paths: `logs/agents.jsonl`
   - Dispatch compatibility/diagnostic stream: `logs/subagent-dispatch.jsonl`
   - Dispatch execution summary: `outputs/orchestration-execution.json`
   - Event fields include additive routing metadata when available: `source`, `dispatch_run_id`, `group_index`
4. Rebuild dashboard artifacts so orchestration, dispatch, and sub-agent telemetry stays visible.

### Optional council planning mode (pre-agreement)

For high-stakes planning quality:
1. Run `council_plan.py` before locking agreement.
2. Default planners use Gemini CLI; OpenAI planners are optional and run through `$apple-keychain` with service `OPENAI_KEY` injected as `OPENAI_API_KEY`.
3. Review:
   - `outputs/council/council-plan.json`
   - `outputs/council/final-plan.md`
4. Agreement gate remains mandatory after council synthesis.

### Dashboard updates (required)

Regenerate:
- `outputs/dashboard.json`
- `outputs/dashboard.md`
- `outputs/dashboard.html`
- via `dashboard_projector.py` (single-writer projector)

Triggers:
- at execution start
- on any job status change
- after each reward eval
- at closeout

At execution start, TheWorkshop must also **auto-open** the dashboard in a new browser window (best-effort, open-once per session) so the user can follow progress without repeated browser churn.
- The HTML auto-refreshes every ~5s by default and can be paused in-page.
- Optional live mode: run `dashboard_server.py` and open the served URL. The page upgrades to SSE (`/events`) when served over HTTP, with file polling fallback preserved.
- Opt-out (tests/CI/headless): set `THEWORKSHOP_NO_OPEN=1`.
- `job_start.py --no-open` is runtime-only and does not mutate project `monitor_open_policy`.
- Persist monitor policy intentionally with `job_start.py --monitor-policy always|once|manual` (or `monitor_runtime.py start --policy ...`).
- TheWorkshop also starts a best-effort background watcher (`dashboard_watch.py`) so the dashboard artifacts keep updating even when no explicit dashboard rebuild trigger fires (opt-out: `THEWORKSHOP_NO_MONITOR=1`).
- Monitor runtime policy is project-scoped (`monitor_open_policy: always|once|manual`) and managed via `monitor_runtime.py start|stop|status`.
- `monitor_runtime.py` is the lifecycle authority for dashboard open/watch/serve/cleanup; compatibility wrappers such as `dashboard_open.py` route through it.
- Live dashboard reuse is intentional: if a healthy local server already exists, runtime state reuses that URL instead of creating a fresh browser target.
- Project terminal closeout stops background dashboard/server runtime and prunes transient runtime artifacts while preserving canonical plans, logs, and dashboard outputs.

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
  - OSS-first env credential `THEWORKSHOP_IMAGEGEN_API_KEY` (preferred, cross-platform)
  - Optional legacy env compatibility aliases: `OPENAI_API_KEY`, `OPENAI_KEY` (low-priority fallback)
  - Keychain fallback provider when env is missing (`apple-keychain` optional dependency)
  - Batch prompts from `artifacts/prompts.jsonl`
  - Output validation + verification logging
- Provider override option:
  - `THEWORKSHOP_IMAGEGEN_CREDENTIAL_SOURCE=auto|env|keychain`
  - `THEWORKSHOP_KEYCHAIN_SERVICE=OPENAI_KEY` (or `THEWORKSHOP_KEYCHAIN_SERVICES=svc1,svc2`)
  - CLI override: `--credential-provider auto|env|keychain`
- Headless/test opt-out for keychain: `THEWORKSHOP_NO_KEYCHAIN=1`
- If keychain approval dialog cannot attach to GUI/TTY, use explicit non-interactive approval:
  - `CODEX_KEYCHAIN_APPROVE=1`

### GitHub mirror (opt-in)

If GitHub is detected or provided, offer mirroring. Do not create external artifacts until enabled.

Once enabled, keep `notes/github-map.json` and issue/milestone status synced.

## Utility Lanes

### Health + Repair

Use `theworkshop health [--repair]` to validate:
- plan topology and dependency consistency
- ID/path consistency
- malformed frontmatter
- stale/orphan state references

`--repair` applies safe-only fixes:
- create missing control-plane paths
- rebuild derived artifacts (sync/tracker/orchestration/dashboard)
- create placeholder artifacts only for non-done jobs

### Quick Tasks

Use `theworkshop quick` for short-path ad-hoc tasks.

Storage:
- `quick/<id>-<slug>/plan.md`
- `quick/<id>-<slug>/summary.md`

Quick tasks are kept out of workstream/job rollup logic but still append project progress entries and refresh dashboard artifacts.
