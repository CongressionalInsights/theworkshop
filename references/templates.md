# Templates

These templates are designed for the restricted YAML-lite parser used by TheWorkshop scripts.

## Project `plan.md`

```md
---
schema: theworkshop.plan.v1
kind: project
id: PJ-YYYYMMDD-###
title: "<project title>"
status: planned
agreement_status: proposed
agreed_at: ""
agreed_notes: ""
started_at: "YYYY-MM-DDTHH:MM:SSZ"
updated_at: "YYYY-MM-DDTHH:MM:SSZ"
completed_at: ""
completion_promise: "PJ-YYYYMMDD-###-DONE"
github_enabled: false
github_repo: ""
subagent_policy: auto
max_parallel_agents: 3
orchestration_last_status: unknown
orchestration_last_run_at: ""
orchestration_parallel_groups: []
orchestration_critical_path: []
---

# Goal

Describe the goal in plain language.

# Acceptance Criteria

- ...

# Workstreams

| Workstream | Status | Purpose |
| --- | --- | --- |
| WS-... | planned | ... |

# Success Hook

- Acceptance criteria: (link above)
- Verification: run `scripts/plan_check.py` and confirm outputs exist
- Completion promise: `<promise>PJ-...-DONE</promise>`

# Progress Log

- YYYY-MM-DDTHH:MM:SSZ started planning

# Decisions

- YYYY-MM-DDTHH:MM:SSZ: ...

# Lessons Learned (Links)

- notes/lessons-learned.md

# Compatibility Notes

- schema: theworkshop.plan.v1
```

## Workstream `plan.md`

```md
---
schema: theworkshop.plan.v1
kind: workstream
id: WS-YYYYMMDD-###
title: "<workstream title>"
status: planned
depends_on: []
started_at: ""
updated_at: ""
completed_at: ""
completion_promise: "WS-YYYYMMDD-###-DONE"
jobs: []
---

# Purpose (How This Supports The Project Goal)

...

# Jobs

| Work Item | Status | Title | Wave | Depends On |
| --- | --- | --- | --- | --- |
| WI-... | planned | ... |  |  |

# Dependencies

Workstream-level dependencies.

# Success Hook

- Acceptance criteria: jobs done + workstream summary exists
- Verification: `scripts/plan_check.py`
- Completion promise: `<promise>WS-...-DONE</promise>`

# Progress Log

...

# Lessons Learned (Links)

...
```

## Job `plan.md`

```md
---
schema: theworkshop.plan.v1
kind: job
work_item_id: WI-YYYYMMDD-###
title: "<job title>"
status: planned
depends_on: []
wave_id: ""
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
updated_at: ""
completed_at: ""
completion_promise: "WI-YYYYMMDD-###-DONE"
outputs:
  - "outputs/<primary>.md"
verification_evidence:
  - "artifacts/verification.md"
reward_last_score: 0
reward_last_eval_at: ""
reward_last_next_action: ""
truth_last_status: unknown
truth_last_failures: []
truth_last_checked_at: ""
orchestration_group_id: ""
orchestration_group_rank: 0
github_issue_number: ""
github_issue_url: ""
---

# Objective

...

# Inputs

...

# Outputs

...

# Acceptance Criteria

- ...

# Verification

How we'll prove acceptance criteria are met.

# Success Hook

- Completion promise: `<promise>WI-...-DONE</promise>`

# Tasks

- [ ] ...

# Progress Log

...

# Notes / Edge Cases

...

# Relevant Lessons Learned

...
```

## Job `prompt.md` (Ralph-ready)

```md
You are working on Job WI-... in project PJ-....

Objective:
- ...

Write outputs to:
- workstreams/<WS...>/jobs/WI-.../outputs/...

Acceptance Criteria:
- ...

Verification:
- ...

Only when all acceptance criteria are satisfied and verification evidence exists, output:
<promise>WI-...-DONE</promise>
```

## Imagegen Job Add-On (Template Snippet)

Use this snippet when a job is responsible for generating image assets:

```md
---
outputs:
  - outputs/asset-index.md
  - outputs/images/cover.png
  - outputs/images/diagram-architecture.png
  - outputs/images/diagram-loop.png
  - outputs/images/diagram-monitoring.png
verification_evidence:
  - artifacts/verification.md
  - artifacts/prompts.jsonl
---

# Inputs

- `artifacts/prompts.jsonl` (one JSON object per line, each with `prompt`; optional `out`)

# Outputs

- `outputs/images/*.png`
- `outputs/asset-index.md`
- project mirror: `../../../../outputs/images/*.png` (via `imagegen_job.py --mirror-project`)

# Verification

- Run:
  - `theworkshop imagegen-job --project <project> --work-item-id WI-...`
- Confirm declared PNG outputs exist and are non-empty.
- Confirm dimensions in `artifacts/verification.md`.
```
