# Rewards (Behavior-Driving)

Rewards are part of completion control, not a standalone "nice to have" score.

## Completion Model

A job may be truthfully marked `done` only when all required gates pass:

1. Agreement gate (project `agreement_status=agreed` before execution/completion)
2. Reward gate (`reward_last_score >= reward_target`)
3. Truth gate (`truth_last_status=pass` and no unresolved truth failures)
4. Dependency/freshness consistency (dependencies done, required outputs/evidence present and non-empty)

Scripts that enforce this model:
- `scripts/reward_eval.py`
- `scripts/truth_eval.py`
- `scripts/plan_check.py`
- `scripts/job_complete.py`

## Required Job Fields

Job frontmatter should include:
- `stakes: low|normal|high|critical`
- `reward_target`
- `max_iterations`
- `iteration`
- `rework_count`
- `rework_reason`
- `reward_last_score`
- `reward_last_eval_at`
- `reward_last_next_action`

Status vocabulary remains fixed:
- `planned | in_progress | blocked | done | cancelled`

## Defaults by Stakes

- low: `reward_target=70`, `max_iterations=2`
- normal: `reward_target=80`, `max_iterations=3`
- high: `reward_target=90`, `max_iterations=5`
- critical: `reward_target=95`, `max_iterations=7`

## Score Components (Deterministic)

`reward_eval.py` computes objective components, then applies penalties.

Primary components:
- Acceptance + outputs quality/completeness
- Verification plan + verification evidence coverage
- Plan hygiene (status/timestamps/progress updates)
- Tracker/dashboard update health
- Lessons application/capture
- Execution-log health for the WI
- GitHub parity (when GitHub mirroring is enabled)

Penalties:
- repeated rework without improvement
- iteration budget exceedance

## TruthGate Interaction (Hard Block)

Truth failures always block truthful completion.

If `truth_last_status != pass` or `truth_last_failures` is non-empty:
- reward may still be computed,
- but completion remains blocked,
- and `job_complete.py` will not emit a done promise.

## Iteration Budget Behavior

If `iteration > max_iterations`:
- job transitions to `blocked`
- completion is denied until a decision is recorded (for example: increase budget, re-scope/split, or adjust stakes/target)

## Deterministic Next-Action Hints

`reward_eval.py` writes `reward_last_next_action` based on first failing condition, with stable priority:

1. truth failures
2. missing outputs
3. missing verification evidence
4. placeholder/weak acceptance criteria
5. placeholder/weak verification plan
6. stale/missing dashboard or task tracker artifacts
7. insufficient execution log evidence
8. GitHub parity gaps when mirroring is enabled
9. final QA/log hygiene reminder

## Completion Promise Rule

Only emit a completion promise when completion is objectively true:

`<promise>WI-...-DONE</promise>`

If any gate fails, do not emit the promise and keep the job in `in_progress` or `blocked` as appropriate.
