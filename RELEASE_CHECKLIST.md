# Release Checklist (`v0.2.3` Baseline)

## 1. Packaging Hygiene (Hardening PR)

- [ ] Confirm source-of-truth layout only:
  - `scripts/`, `references/`, `schemas/`, `examples/sample-project/`, `docs/assets/`, root docs, `.github/`
- [ ] Confirm runtime artifacts are ignored and untracked:
  - `PJ-*`, `_test_runs/`, root `outputs/`, `logs/`, `tmp/`, `artifacts/`, `notes/`
- [ ] Confirm architecture image exists at `docs/assets/theworkshop-systems-architecture.png`
- [ ] Confirm docs asset generation path works:
  - `python3 scripts/generate_docs_assets.py --dry-run`
  - `docs/assets/prompts.jsonl`
- [ ] CI workflow present and active: `.github/workflows/ci.yml`

## 2. Documentation Truth (Feature-Pack PR)

- [ ] `README.md` reflects current behavior and install/update path
- [ ] `SKILL.md` matches runtime/operator contract
- [ ] Docs clearly distinguish the **public OSS baseline** from private/custom local workflows
- [ ] Docs consistently describe optional adapters vs core workflow behavior
- [ ] Gate semantics are consistent across docs (agreement/dependency+freshness/truth/reward)
- [ ] Agent surface docs are consistent:
  - shared cross-repo agents in `~/.codex/agents/*.toml`
  - canonical runtime agents in `.codex/agents/*.toml`
  - canonical runtime limits in `.codex/config.toml`
  - canonical planning metadata in `references/agents/*.json`
  - canonical job-local selector is `agent_profile`
  - `agent_type_hint` appears only as historical migration data
- [ ] Learning-promotion semantics are consistent across docs:
  - staged memory proposals in `.theworkshop/memory-proposals/*.json`
  - staged lesson candidates in `.theworkshop/lessons-candidates/*.json`
  - only parent/curator paths promote durable memory and canonical lessons
  - loop runs promote staged learning only after terminal state
- [ ] Context-lock semantics are consistent across docs:
  - `theworkshop discuss` writes `notes/context/*.md`
  - `context_required` / `context_ref` gating is described consistently
  - delegated and looped work reopen `context_ref`, honor `locked_decisions`, and keep `deferred_ideas` out of scope until refreshed
- [ ] Telemetry semantics are consistent across docs:
  - canonical subagent telemetry in `logs/agents.jsonl`
  - compatibility dispatch telemetry in `logs/subagent-dispatch.jsonl`
- [ ] Billing and spend semantics are consistent (`subscription_auth|metered_api|unknown`)
- [ ] Image credential semantics are consistent (`THEWORKSHOP_IMAGEGEN_API_KEY` env-first + compatibility aliases)

## 3. Release-Gate Tests

Run before merging feature-pack PR and before tagging:

```bash
python3 scripts/transition_done_guard_test.py
python3 scripts/transition_cancel_cascade_test.py
python3 scripts/job_complete_no_tentative_done_test.py
python3 scripts/truth_gate_pdf_test.py
python3 scripts/stale_invalidation_test.py
python3 scripts/orchestrate_plan_test.py
python3 scripts/dispatch_orchestration_test.py
python3 scripts/resolve_agent_profile_test.py
python3 scripts/normalize_agent_profiles_test.py
python3 scripts/dispatch_monitor_policy_test.py
python3 scripts/council_plan_test.py
python3 scripts/dashboard_ui_interaction_test.py
python3 scripts/dashboard_log_readability_test.py
python3 scripts/agent_log_dashboard_test.py
python3 scripts/dashboard_cost_panel_test.py
python3 scripts/dashboard_subscription_cost_display_test.py
python3 scripts/imagegen_job_test.py
python3 scripts/imagegen_keychain_retry_test.py
python3 scripts/doctor_test.py
python3 scripts/council_plan_adapter_boundary_test.py
python3 scripts/oss_packaging_docs_test.py
python3 scripts/job_profile_test.py
python3 scripts/lessons_apply_test.py
python3 scripts/learning_curate_test.py
python3 scripts/loop_job_test.py
python3 scripts/plan_check_content_quality_test.py
python3 scripts/skill_autoresearch_eval_test.py
python3 scripts/skill_surface_contract_score.py --repo .
python3 scripts/smoke_test.py
python3 scripts/sample_scenario_test.py
```

## 4. Release Packaging (`v0.2.3`)

- [ ] Add/update `releases/v0.2.3.md` with final release notes
- [ ] Update `CHANGELOG.md` with consolidated `v0.2.3` release section
- [ ] Merge feature-pack PR to `main`
- [ ] Tag and publish release:

```bash
git tag v0.2.3
git push origin v0.2.3
```

- [ ] Verify release page body matches `releases/v0.2.3.md`

## 5. GitHub Metadata + Triage

Repository metadata (manual):

- Description: `Codex/Claude Code skill for non-coding work with TruthGate, orchestration, monitoring, and spend visibility.`
- Topics: `codex-skill`, `claude-code`, `workflow`, `project-os`, `automation`, `non-coding`

Triage labels (idempotent):

```bash
gh label create "status:needs-repro" --color C5DEF5 --description "Needs reproducible steps" || true
gh label create "status:accepted" --color 0E8A16 --description "Accepted into roadmap" || true
gh label create "status:out-of-scope" --color BFDADC --description "Outside project scope" || true
gh label create "type:bug" --color D73A4A --description "Bug report" || true
gh label create "type:enhancement" --color A2EEEF --description "Enhancement request" || true
gh label create "docs" --color 0075CA --description "Documentation" || true
```

## 6. Post-Release Health

- [ ] `README` release badge resolves latest tag
- [ ] `python3 scripts/doctor.py --profile codex` passes in the intended Codex release environment
- [ ] `python3 scripts/doctor.py --profile portable` passes in the portable/core public baseline environment
- [ ] Issue templates and PR template render correctly
- [ ] Pinned discussion / known limitations issue updated for current release
- [ ] `Unreleased` section in `CHANGELOG.md` reset for next cycle
