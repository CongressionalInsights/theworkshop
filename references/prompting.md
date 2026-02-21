# Prompting Guide (TheWorkshop)

This file describes how the agent should turn a raw user request into an optimized Project → Workstreams → Jobs plan with success hooks.

## Intake questions (outcome-first)

Ask for:
- Who is the audience for the deliverable?
- What exact artifacts should exist when we’re done?
- What is the deadline (if any)?
- Which tradeoff matters most (speed / polish / depth)?

## Decomposition rules of thumb

- Prefer 3–6 workstreams.
- Prefer jobs that are verifiable in 10–90 minutes of focused work.
- Each job should have one dominant output and one dominant verification path.

## Optimization checklist (must do)

- Split oversized jobs:
  - Multiple unrelated outputs
  - Vague acceptance criteria
  - `estimate_hours` too high
- Merge tiny jobs:
  - Pure overhead without increasing verifiability
- Dependencies:
  - Remove “nice to have” dependencies
  - Convert to parallel where possible
- Waves (timeboxes):
  - Use waves for deadlines, stakeholder checkpoints, or large job graphs

## Success hooks: make them loop-safe

Bad acceptance criteria:
- “Make it good”
- “Polish it”

Good acceptance criteria:
- “Create `outputs/brief.md` with sections A/B/C and at least 5 cited sources.”
- “Create `outputs/dashboard.html` that loads without external assets and includes status pills for all jobs.”

Verification should reference on-disk evidence:
- File existence checks
- Script checks (`plan_check.py`)
- Structured reports (`reward_eval.py` output)

Completion promises must be objectively true and only emitted at the end:
- `<promise>WI-20260214-001-DONE</promise>`

## Looping planning prompt (before execution)

Add a short planning decision step before execution:

- "Should this job use loop mode?"
- "Loop mode: `until_complete`, `max_iterations`, or `promise_or_max`?"
- "Loop cap: use project default by stakes (`low=2`, `normal=3`, `high=5`, `critical=7`) or override with a specific integer?"
- "Completion promise for loop stop when in promise-based mode: `<promise>{WI}-DONE</promise>`?"

Capture decisions in project `# Decisions` with:
- `loop_enabled: true/false`
- `loop_mode: ...`
- `loop_max_iterations: N`
- `loop_target_promise: ...`

Then run the execution command chosen for this WI:

- `theworkshop loop --project <path> --work-item-id WI-...`
- append `--mode`, `--max-loops`, `--completion-promise`, and `--max-walltime-sec` as needed

## Agreement gate language (recommended)

Use a short confirmation question:
- “Confirm this structure (workstreams + jobs + success hooks) before I start executing?”

Then record:
- `agreement_status: agreed`
- `agreed_at: ...`
- `agreed_notes: ...`
