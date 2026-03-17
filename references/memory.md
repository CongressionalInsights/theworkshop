# Durable Memory

Durable memory is separate from normal job outputs and separate from lessons learned.

## Authority

Durable memory lives in Codex memory files:
- project memory: `$CODEX_HOME/memories/projects/<Project>.md`
- global memory: `$CODEX_HOME/memories/global.md`

## Policy

- Subagents may read durable memory when it is relevant context.
- Normal explorer / worker / reviewer agents must not edit durable memory files directly.
- Durable memory promotion is parent-controlled or curator-controlled only.
- Only promote stable items:
  - workflow rules
  - durable decisions
  - repeated pitfalls
  - enduring follow-up rules
- Never promote:
  - raw logs
  - transient debugging notes
  - one-off retries
  - ephemeral iteration noise

## Staged Proposal Flow

Write staged proposals to:
- `.theworkshop/memory-proposals/*.json`

Each staged proposal may carry `agent_id` when the candidate belongs to a specific delegated run. Manual/external closeout should promote proposals through `theworkshop agent-closeout`, which passes `agent_id` to the curator so only that run's staged records are considered.

Primary scripts:
- capture: `scripts/memory_proposal_capture.py`
- curate/promote: `scripts/memory_curate.py`

Curator output:
- updates project/global memory files
- marks staged proposals as `promoted` or `skipped`

## Loop + Delegation Rules

- Delegated and looped work should stage durable memory proposals instead of editing memory files directly.
- Loop attempts may capture proposal candidates during execution.
- Promotion happens only after the loop reaches a terminal state (`completed`, `blocked`, `stopped`, or `error`).
- Manual or external delegated runs should emit lifecycle telemetry with `theworkshop agent-log` during execution and call `theworkshop agent-closeout` exactly once for the terminal event and promotion pass.
