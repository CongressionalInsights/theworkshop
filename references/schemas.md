# Schemas (v1)

TheWorkshop uses **Markdown + YAML frontmatter** as its control plane.

## YAML-lite restrictions (important)

TheWorkshop scripts support a restricted YAML subset:
- Scalars: strings, numbers, booleans
- Lists: `key:` + indented `- item`
- Dicts: `key: value` and nested dicts via indentation
- List items may be dicts (common for waves)

Not supported:
- Multiline scalars (`|` / `>`)
- Anchors/aliases
- Complex quoting/escaping rules
- Flow-style collections like `[a, b]` or `[{...}]` (except the empty forms `[]` / `{}`)

If you need complex content, put it in the Markdown body, not frontmatter.

## `theworkshop.plan.v1`

### Common keys
- `schema` (string, required)
- `kind` (`project|workstream|job`, required)
- `status` (required)
- `started_at`, `updated_at`, `completed_at` (ISO Z strings; empty allowed)
- `cancelled_at` (ISO Z string; additive, optional)
- `completion_promise` (string, required)

### Project keys
- `id` (PJ-..., required)
- `title` (string, required)
- `agreement_status` (`proposed|agreed`, required)
- `agreed_at`, `agreed_notes`
- `github_enabled` (bool)
- `github_repo` (string)
- `monitor_open_policy` (`always|once|manual`)
- `monitor_session_id` (string)
- `last_transition_id` (string)

### Workstream keys
- `id` (WS-..., required)
- `title` (string, required)
- `depends_on` (list of WS IDs)
- `jobs` (list of WI IDs)

### Job keys
- `work_item_id` (WI-..., required)
- `title` (string, required)
- `depends_on` (list of WI IDs)
- `wave_id` (string)
- `estimate_hours` (float)
- `stakes` (`low|normal|high|critical`)
- `reward_target` (int)
- `max_iterations` (int)
- `iteration` (int)
- `rework_count` (int)
- `rework_reason` (string)
- `context_required` (bool)
- `context_ref` (relative path to `notes/context/*.md`)
- `outputs` (list of relative paths)
- `verification_evidence` (list of relative paths)
- `reward_last_score` (int)
- `reward_last_eval_at` (string)
- `reward_last_next_action` (string)
- `uat_last_status` (string: `unknown|pass|fail`)
- `uat_last_checked_at` (string)
- `uat_open_issues` (list of strings)
- `uat_follow_up_actions` (list of strings)
- `loop_enabled` (bool)
- `loop_mode` (string: `until_complete|max_iterations|promise_or_max`)
- `loop_max_iterations` (int)
- `loop_target_promise` (string)
- `loop_status` (string: `active|stopped|completed|blocked|error`)
- `loop_last_attempt` (int)
- `loop_last_started_at` (string)
- `loop_last_stopped_at` (string)
- `loop_stop_reason` (string)
- `github_issue_number` / `github_issue_url` (strings)
- `truth_mode` / `truth_checks` / `truth_required_commands`
- `truth_last_status` / `truth_last_checked_at` / `truth_last_failures` / `truth_input_snapshot`
- `orchestration_mode` / `agent_type_hint` / `agent_profile` / `parallel_group`
- `dispatch_budget` / `retry_limit`

## `theworkshop.githubmap.v1`

Stored in `notes/github-map.json`:
- repo
- enabled
- last_sync_at
- issues: mapping WI → {number,url}
- milestones: mapping WV → {number,url}
- project_board: {id,url} (best-effort)

## `theworkshop.dashboard.v1`

Stored in `outputs/dashboard.json` and rendered into `dashboard.html`/`dashboard.md`.

Additive `tokens.*` fields (no schema bump):
- `cost_source`: `codexbar_exact|estimated_from_rates|none`
- `cost_confidence`: `high|medium|low|none`
- `billing_mode`: `subscription_auth|metered_api|unknown`
- `billing_confidence`: `high|medium|low`
- `billing_reason`: deterministic billing mode resolution summary
- `billed_session_cost_usd`
- `billed_project_cost_usd`
- `api_equivalent_session_cost_usd`
- `api_equivalent_project_cost_usd`
- `display_cost_primary_label`
- `display_cost_secondary_label`
- `estimated_session_cost_usd`
- `estimated_project_cost_usd`
- `project_cost_baseline_tokens`
- `project_cost_delta_tokens`
- `rate_model_key`
- `rate_resolution`
- `cost_breakdown`: `{input_uncached,cached_input,output,reasoning_output}`
- `by_work_item`: list of `{work_item_id,estimated_cost_usd,weight_basis,tokens_allocated}`
- `unattributed_cost_usd`

Additional additive projector fields:
- `projection_seq` (int)
- `projection_warnings` (list of strings)
- `monitor_state` (object with runtime monitor metadata)

## `theworkshop.transition.v1`

Event stream in `logs/events.jsonl`:
- `event` (`snapshot|state_transition|projection_warning|monitor_warning`)
- `transition_id`
- `timestamp`
- `actor`
- `reason`
- `entity_kind`
- `entity_id`
- `path`
- `from_status`
- `to_status`
- optional cascade linkage:
  - `cascade_parent_kind`
  - `cascade_parent_id`

## `theworkshop.context.v1`

Stored in `notes/context/<WS-or-WI>-CONTEXT.md`.

- `schema`
- `target_kind` (`workstream|job`)
- `target_id` (`WS-*|WI-*`)
- `created_at`, `updated_at`
- `locked_decisions` (list of strings)
- `deferred_ideas` (list of strings)
- `notes` (list of strings)

## `theworkshop.uat.v1`

Stored in `outputs/uat/<run-id>-UAT.json` and rendered into `outputs/uat/<run-id>-UAT.md`.

- `schema`
- `run_id`
- `target_kind`, `target_id`
- `status` (`testing|completed`)
- `created_at`, `updated_at`
- `current_index`
- `tests`: list of `{work_item_id,name,expected,status,response,severity,follow_up}`
- `summary`: `{total,passed,failed,skipped,pending}`
- `open_issues`: list of `{work_item_id,severity,reason,follow_up}`

## `theworkshop.health.v1`

Stored in `outputs/health.json`.

- `schema`
- `generated_at`
- `project`
- `status` (`healthy|degraded|broken`)
- `errors`, `warnings`, `info` (issue lists)
- `repairable_count`
- `repairs_suggested`
- `repairs_performed`

## `theworkshop.quick.v1`

Stored in `quick/<id>-<slug>/plan.md` with summary in `quick/<id>-<slug>/summary.md`.

- `schema`
- `kind` (`quick_task`)
- `id`
- `title`
- `status` (`planned|in_progress|done|blocked`)
- `work_item_id` (optional WI linkage)
- `commands` (list of shell commands)
- `created_at`, `updated_at`, `completed_at`
- `summary` (relative path)

## `theworkshop.rewards.v1`

Reward evaluation output format used in `reward_eval.py` (also embedded into dashboard.json).

## `theworkshop.orchestration.v1`

Stored in `outputs/orchestration.json`.

Compatibility notes:
- `parallel_groups` is canonical.
- `groups` is a compatibility alias and may mirror the same content.

## `theworkshop.orchestration-execution.v1`

Stored in `outputs/orchestration-execution.json`.
- `groups[*].results[*]` captures delegated execution outcomes.
- Primary runtime event stream is `logs/agents.jsonl` (canonical for manual + dispatch delegation).
- `logs/subagent-dispatch.jsonl` is compatibility/diagnostic dispatch telemetry.

## JSON schema files (runtime validation)

TheWorkshop ships schema files under `schemas/`:
- `schemas/orchestration.schema.json`
- `schemas/orchestration-execution.schema.json`
- `schemas/truth-report.schema.json`
- `schemas/rewards.schema.json`
- `schemas/dashboard.schema.json`
- `schemas/council-plan.schema.json`

Validate with:

```bash
python3 scripts/schema_validate.py --project /path/to/project
```

## `theworkshop.tokenrates.v1`

Stored in `references/token-rates.json` (with optional project override in `notes/token-rates.override.json`):
- `schema`
- `version`
- `updated_at`
- `default_currency` (USD)
- `fallback_model`
- `models`: map of model key -> `usd_per_1m` rates:
  - `input`
  - `cached_input`
  - `output`
  - `reasoning_output` (optional; falls back to `output`)
- `aliases`: identifier/rate-limit aliases -> canonical model key
