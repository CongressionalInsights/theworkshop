# Mini Dashboard

TheWorkshop generates a lightweight interface under `outputs/`:

- `dashboard.json` (canonical data model)
- `dashboard.md` (readable summary)
- `dashboard.html` (self-contained visual view)

## Monitoring behavior (required)

Once execution begins, TheWorkshop must:
- Build the dashboard artifacts.
- **Auto-open** `outputs/dashboard.html` in a new browser window (best-effort, open-once per session).
- Keep the page readable while it runs: the HTML includes an **auto-refresh controller** (default ~5s) with a visible pause/resume toggle and a stale indicator.
- Start a best-effort **dashboard watcher** that periodically rebuilds dashboard artifacts so the auto-refresh actually has new state to display (otherwise the page can feel “stuck”).

Opt-out (tests/CI/headless): set `THEWORKSHOP_NO_OPEN=1`.
Opt-out (no background watcher): set `THEWORKSHOP_NO_MONITOR=1`.

## Required fields

The dashboard must include:
- Structure: project → workstreams → jobs
- Status indicators
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

This opens the dashboard (open-once) and starts the background watcher.
