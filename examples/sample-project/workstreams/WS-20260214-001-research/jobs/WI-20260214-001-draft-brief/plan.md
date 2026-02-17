---
schema: theworkshop.plan.v1
kind: job
work_item_id: WI-20260214-001
title: "Draft brief"
status: planned
depends_on: []
wave_id: "WV-20260214-001"
priority: 2
estimate_hours: 1.0
due_date: ""
stakes: normal
reward_target: 80
max_iterations: 3
iteration: 0
rework_count: 0
rework_reason: ""
started_at: ""
updated_at: "2026-02-14T00:00:00Z"
completed_at: ""
completion_promise: "WI-20260214-001-DONE"
outputs:
  - "outputs/primary.md"
verification_evidence:
  - "artifacts/verification.md"
reward_last_score: 0
reward_last_eval_at: ""
reward_last_next_action: ""
truth_mode: strict
truth_checks:
  - exists_nonempty
  - freshness
  - verification_consistency
truth_required_commands:
  - plan_check.py
truth_last_status: unknown
truth_last_failures: []
truth_last_checked_at: ""
truth_input_snapshot: "artifacts/input-snapshot.json"
orchestration_mode: auto
agent_type_hint: worker
parallel_group: ""
github_issue_number: ""
github_issue_url: ""
---

# Objective

Create a concise research brief in `outputs/primary.md` with clear, checkable acceptance criteria.

# Inputs

- `inputs/` (optional reference material)
- project/workstream plan context

# Outputs

- `outputs/primary.md`
- `artifacts/verification.md`

# Acceptance Criteria

- `outputs/primary.md` exists and is non-empty.
- `outputs/primary.md` includes the completion promise string.
- `artifacts/verification.md` exists and records what was verified.

# Verification

- Confirm declared outputs and evidence files exist and are non-empty.
- Run `scripts/plan_check.py` at project root.
- Record verification notes in `artifacts/verification.md`.

# Success Hook

- Completion promise: `<promise>WI-20260214-001-DONE</promise>`

# Progress Log

- 2026-02-14T00:00:00Z created sample job skeleton.

# Relevant Lessons Learned

- (none yet)
