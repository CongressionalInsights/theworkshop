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
- `completion_promise` (string, required)

### Project keys
- `id` (PJ-..., required)
- `title` (string, required)
- `agreement_status` (`proposed|agreed`, required)
- `agreed_at`, `agreed_notes`
- `github_enabled` (bool)
- `github_repo` (string)

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
- `outputs` (list of relative paths)
- `verification_evidence` (list of relative paths)
- `reward_last_score` (int)
- `reward_last_eval_at` (string)
- `reward_last_next_action` (string)
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

## `theworkshop.rewards.v1`

Reward evaluation output format used in `reward_eval.py` (also embedded into dashboard.json).

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
