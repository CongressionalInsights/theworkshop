# Changelog

## Unreleased

- Nothing yet.

## 2026-03-17 (`v0.2.3`)

### Autoresearch Harness + Skill-Surface Scoring
- Added an optional repo-local outer-loop tuning harness under `autoresearch/` for improving the OSS skill surface without opening the whole repository to autonomous mutation.
- Added:
  - `scripts/skill_autoresearch_eval.py`
  - `scripts/skill_surface_contract_score.py`
  - `scripts/skill_autoresearch_eval_test.py`
  - `autoresearch/program.md`
  - `autoresearch/benchmark-pack.fast.json`
  - `autoresearch/benchmark-pack.full.json`
- Added partial-credit benchmark support so score regressions and contract gaps can be measured without collapsing everything to binary pass/fail.
- Added scored contract checks for:
  - delegated-role grounding to the current job plan and verification path
  - top-level subagent gate anchoring
  - durable blocker-evidence guidance for delegated and looped work
  - truthful manual/external delegation telemetry and exactly-once closeout guidance
  - staged learning / curator-only durable writes
  - context-lock propagation so delegated and looped work reopen `context_ref`, honor locked decisions, and treat deferred ideas as out of scope
- Updated OSS-facing docs and references (`README.md`, `SKILL.md`, `references/prompting.md`, `references/templates.md`, `references/workflow.md`, `RELEASE_CHECKLIST.md`) to reflect the new harness and the tighter delegated-work contract.

### Subagent Docs + Asset Refresh
- Added a public self-contained explainer page at `docs/subagents.html` covering:
  - the broad Codex subagent model,
  - TheWorkshop planning/runtime/observability layers,
  - dispatch vs manual vs loop execution paths,
  - staged lessons / durable memory promotion,
  - explicit manual closeout through `theworkshop agent-closeout`.
- Added a reproducible docs asset generation path:
  - `python3 scripts/generate_docs_assets.py`
  - `docs/assets/prompts.jsonl`
  - `docs/assets/README.md`
- Added reusable generated docs/brand assets:
  - `docs/assets/theworkshop-mark.png`
  - `docs/assets/theworkshop-systems-architecture.png`
  - `docs/assets/subagents-explainer-preview.png`
- Locked the accepted docs art pass to the OpenAI image path:
  - `gpt-image-1.5`
  - keychain service `OPENAI_KEY` injected as `OPENAI_API_KEY`
- Refreshed the systems architecture visual to match the current OSS runtime model:
  - planning metadata and repo config in the control plane,
  - native Codex subagents as the runtime,
  - truthful telemetry, staged learning, and curated closeout as first-class surfaces.
- Updated `README.md` and `docs/subagents.html` to use the generated PNG asset set.

### Repo-Only OSS Packaging Pass
- Reframed the repo as the **public OSS baseline** for TheWorkshop, distinct from any private/custom local operator overlays.
- Added a profile-aware preflight surface:
  - `python3 scripts/doctor.py --profile codex|portable`
- Reclassified public integrations as **optional adapters** in docs and adapter-backed command behavior:
  - Codex telemetry / CodexBar
  - Gemini / OpenAI council planners
  - Apple Keychain
  - imagegen skill bridge
  - GitHub mirroring
- Added shared runtime-profile helper logic so sibling-skill paths and adapter detection are not hard-coded independently across scripts.
- Added regression coverage for:
  - portable vs codex doctor behavior
  - optional council planner adapter boundary
  - OSS packaging docs consistency

## 2026-03-02 (`v0.2.2`)

### Monitor Policy Hardening
- `job_start.py --no-open` is now runtime-only and no longer persists `monitor_open_policy=manual`.
- Added explicit persistent monitor policy override:
  - `job_start.py --monitor-policy always|once|manual`
- Dashboard docs now clarify policy precedence and persistent-vs-ephemeral behavior.

### Strict Completion Evidence Gates (Forward Strict)
- New jobs created by `scripts/job_add.py` now default to strict completion evidence requirements:
  - `execution_log_required: true`
  - `execution_log_exemption_reason: ""`
  - `lesson_capture_required: true`
  - `lesson_capture_exemption_reason: ""`
- New truth checks added and enabled by default for new jobs:
  - `work_item_execution_logged`
  - `linked_lesson_captured`
- `scripts/truth_eval.py` now enforces:
  - WI execution evidence presence in `logs/execution.jsonl` (or explicit exemption),
  - linked substantive lesson capture in `notes/lessons-index.json` (or explicit exemption).

### Plan/Reward Alignment
- `scripts/plan_check.py` now rejects `done` jobs that require execution logs or linked lessons when those requirements are unmet and not exempted.
- `scripts/reward_eval.py` now emits deterministic next actions for:
  - missing required execution evidence,
  - missing required linked lesson capture.

### Compatibility
- Legacy jobs remain backward compatible:
  - jobs without the new requirement fields are treated as non-strict unless explicitly opted in.

### Regression Coverage and Docs
- Added:
  - `scripts/job_start_monitor_policy_test.py`
  - `scripts/strict_completion_requirements_test.py`
- Updated:
  - `scripts/required_command_logged_test.py`
- Updated operator/reference docs:
  - `SKILL.md`
  - `references/workflow.md`
  - `references/dashboard.md`
  - `references/lessons.md`
  - `references/rewards.md`

## 2026-02-28 (`v0.2.1`)

### Lessons Application + Ranking
- Added `scripts/lessons_apply.py` and CLI alias `theworkshop lessons-apply` for deterministic job-level lessons insertion.
- `job_start.py` now applies lessons by default before transition to `in_progress`.
- Added job-start controls:
  - `--no-apply-lessons`
  - `--lessons-limit`
  - `--lessons-include-global`
- Upgraded lesson ranking (`scripts/lessons_query.py`) to include:
  - text similarity over snippet/context/worked/failed/recommendation
  - tag overlap
  - linked ID overlap (`WI/WS/PJ`)
  - recency and deterministic tie-breakers
- Expanded `notes/lessons-index.json` generation (`scripts/lessons_capture.py`) with additive fields:
  - `captured_at`, `context`, `worked`, `failed`, `recommendation`

### Job Scaffolding Profiles
- Added `--job-profile {default,investigation_attribution,identity_resolution}` to `scripts/job_add.py`.
- New profile scaffolds prefill stronger objective/acceptance/verification/output templates for:
  - attribution sweeps
  - same-entity/identity resolution workflows

### Content-Quality Gates
- `scripts/reward_eval.py` now computes specificity diagnostics and applies deterministic penalties for weak/boilerplate sections.
- `scripts/plan_check.py` now enforces content quality by lifecycle phase:
  - `planned`: warnings
  - `in_progress` / `done`: hard failures on placeholder/weak content

### CI + Regression Coverage
- Added CI execution coverage for:
  - `scripts/job_profile_test.py`
  - `scripts/lessons_apply_test.py`
  - `scripts/plan_check_content_quality_test.py`
- Added new regression tests for:
  - profile scaffolding correctness
  - lessons apply idempotency and opt-out behavior
  - strict content-quality gate behavior

### Opportunity Map Integration (am-will/codex-skills inspired)
- Added executable orchestration dispatch:
  - new `scripts/dispatch_orchestration.py` and CLI `theworkshop dispatch`
  - executes runnable orchestration groups with dependency checks, bounded parallelism, and structured dispatch telemetry
  - writes `logs/subagent-dispatch.jsonl` and `outputs/orchestration-execution.json`
- Added role profile registry + resolver:
  - `references/agents/{explorer,worker,reviewer}.json`
  - `scripts/resolve_agent_profile.py` to operationalize `agent_type_hint`, `stakes`, and `orchestration_mode`
- Added optional council planning flow:
  - `scripts/council_plan.py` and CLI `theworkshop council-plan`
  - supports Gemini planner/judge mode by default
  - supports optional OpenAI planner mode through `$apple-keychain` with `OPENAI_KEY` injected as `OPENAI_API_KEY`
  - writes `outputs/council/council-plan.json` and `outputs/council/final-plan.md`
- Added schema hardening:
  - shipped JSON schemas under `schemas/`
  - added `scripts/schema_validate.py` and CLI `theworkshop schema-validate`
  - integrated schema checks into `scripts/plan_check.py` for present machine artifacts
- Added optional live dashboard transport:
  - `scripts/dashboard_server.py` and CLI `theworkshop dashboard-serve`
  - dashboard now supports SSE live mode over HTTP (`/events`) with file polling fallback preserved
  - dashboard payload/render includes dispatch engine telemetry
- Added install ergonomics:
  - `scripts/install_skill.sh` for copy/symlink install into `$CODEX_HOME/skills/theworkshop`
- Added regression tests:
  - `scripts/resolve_agent_profile_test.py`
  - `scripts/dispatch_orchestration_test.py`
  - `scripts/council_plan_test.py`
  - `scripts/schema_validate_test.py`
  - `scripts/dashboard_server_test.py`

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

## 2026-02-27 (`v0.2.0`)

### Public OSS Baseline Refresh
- Published the current open-source baseline for `CongressionalInsights/theworkshop` with hardened packaging, updated release operations, and CI validation for critical regression paths.
- Added `.github/workflows/ci.yml` for push/PR verification (Python syntax + core regression suite).
- Refreshed release operations guidance in `RELEASE_CHECKLIST.md` for two-step hardening + feature-pack rollout and on-demand release cadence.
- Added `releases/v0.2.0.md` as the canonical release body for `v0.2.0`.

### Lifecycle and Completion Integrity
- Canonical transition engine (`transition.py`) governs project/workstream/job state movement, with `done` and `cancelled` as first-class terminal outcomes.
- Completion pathways remain fail-closed under multi-gate semantics: agreement, dependency/freshness, truth, and reward.
- Expanded stale invalidation and consistency checks to reduce false completion and drift between plans, status rollups, and downstream dependencies.

### Orchestration and Delegation
- Shipped executable orchestration dispatch (`dispatch_orchestration.py`) tied to runnable plan groups and dependency-safe scheduling.
- Added role resolution and optional council planning paths (`resolve_agent_profile.py`, `council_plan.py`) with schema-backed output validation.
- Preserved dual execution modes (manual and dispatch) while standardizing dashboard semantics around canonical agent telemetry.

### Dashboard, Monitoring, and Spend
- Reinforced single-writer dashboard projection model and monitor runtime controls for deterministic status visibility.
- Added readability-first event rendering, concise live activity text, and raw payload details drawers for debug depth.
- Standardized billing-aware spend display (`subscription_auth|metered_api|unknown`) with API-equivalent estimate surfacing.

### Image and Credential Reliability
- Kept env-first image credential path (`THEWORKSHOP_IMAGEGEN_API_KEY`) as canonical for OSS portability.
- Preserved compatibility aliases (`OPENAI_API_KEY`, `OPENAI_KEY`) and optional keychain-based compatibility flows.

### Test Surface
- Expanded and maintained regression scripts across lifecycle, truth/reward gates, orchestration, dashboard telemetry/readability, billing, and credentials.

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
