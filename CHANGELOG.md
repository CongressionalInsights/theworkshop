# Changelog

## Unreleased

### GSD Pattern Adoptions (TheWorkshop)
- Added intent-locking flow via `scripts/discuss.py` and CLI `theworkshop discuss`.
  - Captures/locks pre-execution context in `notes/context/<WS-or-WI>-CONTEXT.md`.
  - Supports merge/replace updates and explicit `context_required` gating for jobs.
- Added resumable human verification via `scripts/verify_work.py` and CLI `theworkshop verify-work`.
  - Persists UAT artifacts to `outputs/uat/<run-id>-UAT.md` and `outputs/uat/<run-id>-UAT.json`.
  - Routes failed checks into structured follow-up actions and completion gate blockers.
- Added project-integrity checks via `scripts/health.py` and CLI `theworkshop health [--repair]`.
  - Validates frontmatter integrity, id/path consistency, dependency references, cycles, stale references, and context gate health.
  - `--repair` performs safe-only auto-fixes and rebuilds derived artifacts.
- Added short-path ad-hoc execution via `scripts/quick.py` and CLI `theworkshop quick`.
  - Isolates one-off tasks under `quick/<id>-<slug>/`.
  - Preserves control-plane visibility by logging quick runs into project progress and dashboard rebuild paths.
- Added centralized utility layer `scripts/tw_tools.py` for shared logic:
  - frontmatter/section helpers
  - discovery and context-gate validation helpers
  - common script runner and rollup helpers
- Extended control-plane gates and scoring:
  - `job_start.py`, `job_complete.py`, and `plan_check.py` now enforce context/UAT gate semantics.
  - `reward_eval.py` now includes UAT-aware penalties and next-action routing.
- Added additive schema-compatible fields for jobs:
  - `context_required`, `context_ref`
  - `uat_last_status`, `uat_last_checked_at`, `uat_open_issues`, `uat_follow_up_actions`
- Added regression coverage for the new flows in `scripts/workflow_extensions_test.py` and updated smoke checks in `scripts/smoke_test.py`.

### Public Launch Baseline (`v0.1.0`)
- Prepared GitHub-first open-source packaging for adoption/trust with lean maintainer overhead.
- Promoted a canonical systems architecture diagram to `docs/assets/theworkshop-systems-architecture.png` and linked it from `README.md`.
- Reworked root documentation into an OSS-oriented entrypoint: install, quickstart, gate model, reliability posture, imagegen path, and roadmap.
- Added community and governance docs: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `SUPPORT.md`.
- Refactored image-generation credentialing for OSS safety and portability:
  - New canonical env var: `THEWORKSHOP_IMAGEGEN_API_KEY` (preferred).
  - Legacy compatibility aliases retained: `OPENAI_API_KEY`, `OPENAI_KEY`.
  - Optional keychain provider mode via `THEWORKSHOP_IMAGEGEN_CREDENTIAL_SOURCE=keychain` and optional `$apple-keychain` runner.
  - Added provider-aware credential checks in `scripts/doctor.py` and env/keychain resolution helpers in `scripts/imagegen_job.py`.
  - Added explicit provider-override controls (`auto|env|keychain`) in imagegen runner documentation and CLI help text.
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
- Standardized image credentialing around `THEWORKSHOP_IMAGEGEN_API_KEY` with legacy `OPENAI_API_KEY` compatibility, and optional keychain fallback for macOS.
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

## 2026-02-22 (`v0.1.1`)

### Open-Source Credential Baseline
- Refactored image generation authentication to a provider-agnostic contract owned by TheWorkshop.
- Introduced canonical OSS key: `THEWORKSHOP_IMAGEGEN_API_KEY` (env-first default, cross-platform).
- Kept compatibility fallbacks for `OPENAI_API_KEY` and `OPENAI_KEY`.
- Added optional explicit keychain provider mode:
  - `THEWORKSHOP_IMAGEGEN_CREDENTIAL_SOURCE=keychain`
  - optional `THEWORKSHOP_KEYCHAIN_RUNNER`
  - optional service override via `THEWORKSHOP_KEYCHAIN_SERVICE(S)`
- Updated docs (`README.md`, `SKILL.md`, `references/workflow.md`, `references/prompting.md`, `references/templates.md`) for provider-first setup.
- Updated `scripts/imagegen_job.py` with `auto|env|keychain` resolution and env-first command execution behavior.
- Updated `scripts/doctor.py` to pass on env-only credentials and treat keychain as optional.
- Added credential provider tests:
  - env-only success and env-failure guidance in `scripts/imagegen_job_test.py`
  - env-required preflight behavior in `scripts/doctor_test.py`
