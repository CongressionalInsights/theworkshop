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
job_profile: "default"
context_required: false
context_ref: ""
loop_enabled: false
loop_mode: max_iterations
loop_max_iterations: 0
loop_target_promise: ""
loop_status: ""
loop_last_attempt: 0
loop_last_started_at: ""
loop_last_stopped_at: ""
loop_stop_reason: ""
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
uat_last_status: unknown
uat_last_checked_at: ""
uat_open_issues: []
uat_follow_up_actions: []
orchestration_group_id: ""
orchestration_group_rank: 0
github_issue_number: ""
github_issue_url: ""
---

# Objective

State a task-specific objective tied to `<job title>` with scope/entity constraints.

# Inputs

...

# Outputs

List concrete output paths and keep them aligned with `outputs:` frontmatter.

# Acceptance Criteria

- At least 2 objective, checkable bullets.
- Include any attribution/disambiguation requirements when relevant.

# Verification

Describe deterministic checks and explicit evidence files under `artifacts/`.

# Success Hook

- Completion promise: `<promise>WI-...-DONE</promise>`

# Tasks

- [ ] ...

# Progress Log

...

# Notes / Edge Cases

...

# Relevant Lessons Learned

- Auto-populated at job start via `lessons-apply`; keep applied lessons actionable.
```

## Job Profile Variants

Use `job_add.py --job-profile` for stronger defaults:

- `default`: single-output general purpose jobs (`outputs/primary.md`).
- `investigation_attribution`: prefilled for attribution sweeps (`candidate_ranked.md`, hit CSVs, query audit, evidence matrix).
- `identity_resolution`: prefilled for same-entity analysis (name normalization, timeline overlap, determination report).

## Job `prompt.md` (Ralph-ready)

```md
You are working on Job WI-... in project PJ-....

Re-open the current job plan and any existing outputs/evidence before making changes. Filesystem state persists across attempts; chat memory does not.
If `context_ref` is set on the job, reopen that context file before editing. Treat locked decisions as binding scope constraints and deferred ideas as out of scope until the parent thread refreshes the context lock.

Objective:
- ...

Stay inside this work-item scope. Do not change unrelated files.

Write outputs to:
- workstreams/<WS...>/jobs/WI-.../outputs/...

Acceptance Criteria:
- ...

Verification:
- ...
- Re-run the declared verification steps and update evidence under `artifacts/`.

If blocked:
- Leave durable blocker evidence in the work-item artifacts or notes before stopping.

Only when all acceptance criteria are satisfied and verification evidence exists, output:
<promise>WI-...-DONE</promise>
```

## Job Loop Planning Snippet

Add the following in job planning notes when loop mode is planned:

```md
# Loop Plan

- loop_enabled: true
- loop_mode: promise_or_max
- loop_max_iterations: 5
- loop_target_promise: WI-...-DONE

If the mode is `until_complete` or `promise_or_max`, ensure the objective/verification requires a deterministic completion promise.
If `loop_enabled` is false, execute with a single-shot command path (`job_start` + `job_complete`).
```

## Context Lock Note

Use this note when a work item requires pre-execution alignment through `theworkshop discuss`:

```md
Context lock:
- Re-open `context_ref` before changing files or artifacts.
- Treat locked decisions as binding scope constraints for this run.
- Treat deferred ideas as explicitly out of scope until the parent thread refreshes the context lock.
```

## Manual/External Delegation Note

Use this note when a plan or prompt relies on manual/external delegation outside dispatch:

```md
Delegation telemetry:
- Use `theworkshop agent-log` for spawned/progress/intermediate lifecycle events.
- Use `theworkshop agent-closeout` exactly once for the terminal event.
- Keep delegated status truthful in project artifacts/logs instead of relying on chat-only updates.
```

## Staged Learning Note

Use this note when delegated or looped work may discover reusable lessons or durable workflow guidance:

```md
Learning capture:
- Stage memory proposals and lesson candidates first.
- Do not edit durable memory files or canonical lesson artifacts directly.
- Let curator agents or the parent thread promote staged findings later.
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
- Configure credentials once per environment:
  - `export THEWORKSHOP_IMAGEGEN_API_KEY=...` (recommended)
  - Optional legacy: `export OPENAI_API_KEY=...` for existing local setups
- Confirm declared PNG outputs exist and are non-empty.
- Confirm dimensions in `artifacts/verification.md`.
```
