# Compatibility

## Versioning Rules

- Schemas are versioned (for example: `theworkshop.plan.v1`, `theworkshop.dashboard.v1`).
- Within `v1`, changes are additive-only:
  - new keys may be added
  - new sections may be added
  - existing required headings/anchors must not be renamed or removed
- Breaking changes require a new major version (for example `v2`) and a migration helper.

## YAML-Lite Constraints

TheWorkshop uses a restricted YAML subset for frontmatter.

Supported:
- scalar values (`string`, `number`, `boolean`)
- block lists (`- item`)
- nested mappings using indentation

Not supported:
- multiline scalar blocks (`|`, `>`)
- anchors/aliases
- complex tags
- flow-style collections (except empty placeholders like `[]` and `{}`)

Guideline: keep complex structured content in Markdown body sections, not frontmatter.

## Stable Heading Anchors

These headings are relied on by tooling and should stay stable.

Project plans:
- `# Goal`
- `# Acceptance Criteria`
- `# Workstreams`
- `# Success Hook`
- `# Progress Log`
- `# Decisions`

Workstream plans:
- `# Purpose (How This Supports The Project Goal)`
- `# Jobs`
- `# Dependencies`
- `# Success Hook`
- `# Progress Log`

Job plans:
- `# Objective`
- `# Inputs`
- `# Outputs`
- `# Acceptance Criteria`
- `# Verification`
- `# Success Hook`
- `# Progress Log`
- `# Relevant Lessons Learned`

## Additive Keys (v1 Examples)

Recent additive keys include:

Project-level:
- `subagent_policy`
- `max_parallel_agents`

Job-level truth/orchestration:
- `truth_mode`
- `truth_checks`
- `truth_required_commands`
- `truth_last_status`
- `truth_last_checked_at`
- `truth_last_failures`
- `truth_input_snapshot`
- `orchestration_mode`
- `agent_type_hint`
- `parallel_group`

Dashboard tokens/billing payload (additive):
- `billing_mode`
- `billing_confidence`
- `billing_reason`
- `billed_session_cost_usd`
- `billed_project_cost_usd`
- `api_equivalent_session_cost_usd`
- `api_equivalent_project_cost_usd`
- `display_cost_primary_label`
- `display_cost_secondary_label`

## Orchestration Payload Compatibility

`outputs/orchestration.json` compatibility contract:
- `parallel_groups` is canonical
- `groups` is a compatibility alias and may be present for older consumers

Consumers should accept either key, preferring `parallel_groups` when available.

## Unknown Keys and Sections

Tools should preserve unknown frontmatter keys and unknown Markdown sections during read/write operations.

Compatibility rule:
- ignore what you do not understand
- do not discard unknown data

## Migration Trigger (v2)

Create `v2` when any of the following occurs:
- required key rename/removal
- semantic redefinition of existing required fields
- required heading anchor rename/removal
- YAML-lite parser contract break

A migration helper must be provided before adopting the breaking schema.
