# Changelog

## Unreleased

### Public Launch Baseline (`v0.1.0`)
- Prepared GitHub-first open-source packaging for adoption/trust with lean maintainer overhead.
- Promoted a canonical systems architecture diagram to `docs/assets/theworkshop-systems-architecture.png` and linked it from `README.md`.
- Reworked root documentation into an OSS-oriented entrypoint: install, quickstart, gate model, reliability posture, imagegen path, and roadmap.
- Added community and governance docs: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `SUPPORT.md`.
- Added GitHub collaboration scaffolding: issue templates, PR template, and automated close policy for stale `status:needs-repro` reports.
- Added release operations docs: `RELEASE_CHECKLIST.md` and structured notes in `releases/v0.1.0.md`.

### Core Workflow + Gates
- Solidified Project -> Workstreams -> Jobs as the control plane with living plan updates (status, timestamps, progress logs, and rollups).
- Completion semantics are now explicitly multi-gate: agreement before execution, reward score threshold, truth verification, and dependency/freshness consistency.
- `job_complete.py` is fail-closed: jobs are not marked `done` unless all completion gates pass.

### TruthGate and Stale Invalidation
- Added deterministic truth evaluation (`scripts/truth_eval.py`) with artifact-truth checks (not just artifact presence).
- Added dependency input snapshots and stale downstream invalidation flow (`scripts/input_snapshot.py`, `scripts/invalidate_downstream.py`).
- Extended validation so `done` states are rejected when truth checks fail or stale/contradictory verification remains.

### Orchestration + Sub-Agent Telemetry
- Added orchestration planning (`scripts/orchestrate_plan.py`) with runnable grouping and critical path outputs.
- Standardized orchestration payload compatibility: `parallel_groups` is canonical; `groups` is kept as a compatibility alias.
- Added sub-agent event logging (`scripts/agent_log.py`) and dashboard surfacing from `logs/agents.jsonl`.

### Dashboard / Monitoring
- Upgraded dashboard build/rendering with auto-refresh controls, stale indicators, and expanded operational panels.
- Added best-effort auto-open + open-once behavior (`scripts/dashboard_open.py`) and monitor/watcher loop (`scripts/dashboard_monitor.py`, `scripts/dashboard_watch.py`).
- Improved refresh reliability by rebuilding dashboard artifacts on lifecycle transitions and key evaluation updates.

### Loop Execution
- Added first-class loop orchestration via `theworkshop loop` with `--mode {until_complete,max_iterations,promise_or_max}` and optional `--max-walltime-sec`.
- Added optional planning-time loop configuration and loop decision capture in work plan frontmatter and project-level decisions log.
- Added loop state fields (`loop_*`) to the work-item schema and persisted dashboard surfaces so UI shows enabled status, mode, attempts, and stop reason.
- Added loop execution integration tests for success, cap-stop, non-zero codex exit, cancellation, timeout, and malformed promise.

### PDF Truth Test Portability
- Updated `scripts/truth_gate_pdf_test.py` to discover Chrome/Chromium via env overrides + PATH (`THEWORKSHOP_PDF_BROWSER` / `THEWORKSHOP_CHROME_PATH`) instead of hardcoding macOS app paths.
- Added clear skip-path behavior for unsupported environments so CI/open-source users on non-mac systems can still run the suite.

### Billing / Spend Model
- Added token-rate based spend estimation and project baseline/delta accounting.
- Added billing-aware display semantics (`subscription_auth|metered_api|unknown`) with confidence/reason metadata.
- Subscription/auth sessions now display billed marginal cost as `$0` while preserving API-equivalent estimates for optimization.

### Image Generation Reliability
- Added first-class WI image generation runner (`scripts/imagegen_job.py`) with prompts validation, declared-output checks, and verification artifact capture.
- Standardized keychain behavior around canonical `OPENAI_KEY` with compatibility injection as `OPENAI_API_KEY` for imagegen tooling.
- Documented/validated headless approval fallback path (`CODEX_KEYCHAIN_APPROVE=1`) for non-interactive runs.

### Test Coverage
- Expanded scripted regression coverage across status rollups, dependency gates, truth gating, stale invalidation, orchestration, dashboard rendering, token/billing resolution, and imagegen dry-run paths (`scripts/*_test.py`).
- Added subscription-aware dashboard/billing display tests and orchestration compatibility assertions.

### Documentation Refresh
- Rewrote core docs and references for consistency with current behavior (gates, orchestration, monitoring, billing, and imagegen reliability).
- Refreshed sample project artifacts to align examples with current control-plane expectations and plan structure.

### Distribution and Installability
- Added explicit installation and update instructions for open-source users in `README.md` and `SKILL.md`:
  - clone from `https://github.com/CongressionalInsights/theworkshop.git`
  - install under `$CODEX_HOME/skills/theworkshop`
  - update via `git pull origin main`
