# Mini Dashboard

TheWorkshop generates a lightweight interface under `outputs/`:

- `dashboard.json` (canonical data model)
- `dashboard.md` (readable summary)
- `dashboard.html` (self-contained visual view)
- Optional live transport server: `scripts/dashboard_server.py` (HTTP + SSE)

Single-writer rule:
- Lifecycle/orchestration flows should project dashboard artifacts through `scripts/dashboard_projector.py`.
- `dashboard_projector.py` uses a lock + unique temp files + atomic replace to avoid concurrent writer races.

## Monitoring behavior (required)

Once execution begins, TheWorkshop must:
- Build the dashboard artifacts.
- **Auto-open** `outputs/dashboard.html` in a new browser window (best-effort, open-once per session).
- Keep the page readable while it runs: the HTML includes an **auto-refresh controller** (default ~5s) with a visible pause/resume toggle and a stale indicator.
- If opened via `dashboard_server.py` (`http://127.0.0.1:*`), the dashboard upgrades to SSE live mode via `/events`; if SSE is unavailable/disconnected, file polling remains active.
- Start a best-effort **dashboard watcher** that periodically rebuilds dashboard artifacts so the auto-refresh actually has new state to display (otherwise the page can feel “stuck”).

Opt-out (tests/CI/headless): set `THEWORKSHOP_NO_OPEN=1`.
Opt-out (no background watcher): set `THEWORKSHOP_NO_MONITOR=1`.

## Required fields

The dashboard must include:
- Structure: project → workstreams → jobs
- Status indicators
- Loop state on jobs (`loop_enabled`, `loop_mode`, `loop_max_iterations`, `loop_status`, `loop_last_attempt`, `loop_last_stopped_at`, `loop_stop_reason`)
- Dependencies (best-effort)
- Wall-clock elapsed time since `project.started_at`
- Execution log stats from `logs/execution.jsonl`
- Token usage:
  - estimated always (token proxy)
  - exact session cost when CodexBar provides it
  - otherwise estimated USD from session tokens + `references/token-rates.json`
  - optional project override rates from `notes/token-rates.override.json`
  - project delta spend from `logs/token-baseline.json`
  - per-work-item spend allocation (approximate) from `logs/execution.jsonl`
- Rewards: score, target, next action
- Sub-agent telemetry: canonical event stream from `logs/agents.jsonl` (manual + dispatch sources).
- Dispatch telemetry: filtered dispatch-source counts from canonical `logs/agents.jsonl`; `logs/subagent-dispatch.jsonl` is compatibility/diagnostic only.
- Dispatch execution summary from `outputs/orchestration-execution.json`
- Operator readability: event/task logs are normalized for human reading by default (title-first, shortened IDs, severity tags).
- Debug fidelity: full machine payload remains available via per-event details drawers in `dashboard.html`.
- GitHub sync: repo + enabled + last sync (if enabled)

## Spend semantics

- `tokens.billing_mode`: `subscription_auth|metered_api|unknown`
  - `subscription_auth`: billed costs display as `$0.0000` (subscription-included marginal billing), with API-equivalent estimates shown as secondary values.
  - `metered_api`: billed costs display metered values (exact when CodexBar provides them).
  - `unknown`: estimate-first display with uncertainty labels.
- `tokens.billing_confidence`: `high|medium|low`
- `tokens.billing_reason`: short deterministic explanation of how billing mode was resolved.
- Optional override for deterministic behavior: `THEWORKSHOP_BILLING_MODE=subscription_auth|metered_api|unknown`.
- `tokens.cost_source`:
  - `codexbar_exact` when CodexBar provides exact session USD
  - `estimated_from_rates` when using token-rate estimation
  - `none` when no usable token source is available
- `tokens.cost_confidence`: `high|medium|low|none`
- `tokens.by_work_item` and `tokens.unattributed_cost_usd` are allocation estimates, not provider billing truth.

## Update triggers

Regenerate at:
- execution start
- any job status change
- after each reward eval
- closeout

## Manual monitor command

The dispatcher includes a best-effort helper:

- `theworkshop monitor --project <path>`

For SSE live serving:

- `theworkshop dashboard-serve --project <path> --open`

This opens the dashboard (open-once) and starts the background watcher.

For explicit runtime controls:
- `theworkshop monitor-start --project <path> --policy always|once|manual`
- `theworkshop monitor-stop --project <path>`
