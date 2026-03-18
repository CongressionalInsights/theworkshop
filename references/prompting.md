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

Loop-safe prompts should be self-sufficient:
- restate the exact work-item scope and output paths
- name the deterministic verification steps or commands
- point to any existing artifacts the next attempt should inspect first
- assume filesystem state persists but conversational memory does not

For image-asset jobs, planning should include a credential setup note:
- Default env credential: `THEWORKSHOP_IMAGEGEN_API_KEY` (preferred for OSS compatibility).
- Fallback note (legacy): `OPENAI_API_KEY` / `OPENAI_KEY` may continue to work if already configured.
- Avoid hard-coding provider credentials in prompts or templates; keep key material outside project files.

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

When a looped WI uses a custom prompt, make sure it tells each attempt to:
- re-open the current job plan and existing outputs/evidence before making changes
- produce filesystem-visible progress, not just narrative status
- leave durable blocker evidence in artifacts/notes if the attempt cannot proceed
- emit the completion promise only after acceptance criteria and verification evidence are satisfied

## Intent lock before execution (`theworkshop discuss`)

For ambiguous jobs/workstreams, capture decisions before execution:

- `theworkshop discuss --project <path> --work-item-id WI-... --decision \"...\" --defer \"...\"`

Write context in:
- `notes/context/WI-...-CONTEXT.md`

When the job must not run without this alignment, set:
- `context_required: true`
- `context_ref: notes/context/WI-...-CONTEXT.md`

Execution will fail at `job_start` if context is required but missing.

## Manual/External Delegation Truthfulness

When a plan or custom prompt uses manual/external delegation outside dispatch, spell out the telemetry contract up front:

- use `theworkshop agent-log` for spawned/progress/intermediate lifecycle events
- use `theworkshop agent-closeout` exactly once for the terminal event
- keep status truth on disk; do not rely on chat-only summaries to represent delegated state

## Verify-work UAT loop (`theworkshop verify-work`)

After implementation, run conversational UAT:

- `theworkshop verify-work --project <path> --work-item-id WI-...`

This updates job-level UAT fields:
- `uat_last_status`
- `uat_last_checked_at`
- `uat_open_issues`
- `uat_follow_up_actions`

If UAT issues remain open, completion should be blocked until resolved.

## Agreement gate language (recommended)

Use a short confirmation question:
- “Confirm this structure (workstreams + jobs + success hooks) before I start executing?”

Then record:
- `agreement_status: agreed`
- `agreed_at: ...`
- `agreed_notes: ...`
