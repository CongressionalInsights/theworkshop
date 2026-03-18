# Autoresearch Harness

This directory adapts the [karpathy/autoresearch](https://github.com/karpathy/autoresearch) outer-loop idea to `TheWorkshop`.

The key difference is scope:

- do not mutate the whole repo
- do not optimize against incidental internal details
- do mutate the skill surface that changes agent behavior
- do evaluate experiments against reproducible repo checks

## Mutable Surface

The benchmark packs in this directory treat the following files as the default writable surface:

- `README.md`
- `SKILL.md`
- `references/prompting.md`
- `references/workflow.md`
- `references/templates.md`
- `.codex/agents/*.toml`

This keeps the loop focused on operator-facing behavior, prompting guidance, and repo-local agent instructions.

In practice, the scored contract benchmark has been most useful when it creates headroom for operator-facing seams such as:
- delegated-role grounding to the current job plan / verification path
- durable blocker evidence
- truthful manual/external delegation telemetry
- staged learning with curator-only durable promotion
- context-lock propagation through `context_ref`, `locked_decisions`, and `deferred_ideas`

## Packs

- `benchmark-pack.fast.json`: fast regression pack for iteration-to-iteration keep/discard decisions
- `benchmark-pack.full.json`: broader pack to confirm stronger candidates before keeping them long-term

Both packs are executed by:

```bash
python3 scripts/skill_autoresearch_eval.py --pack autoresearch/benchmark-pack.fast.json --diff-ref HEAD~1
```

The evaluator:

- enforces the writable surface by diffing the current commit against `--diff-ref`
- rejects dirty worktrees by default
- runs weighted benchmarks, including optional partial-credit scored benchmarks
- computes a single `0-100` score
- optionally appends run summaries to `state/autoresearch/results.tsv`

Important operating rule:

- keep benchmark-maintenance commits separate from scored skill-surface experiments
- if you change the evaluator or benchmark packs, do that in its own commit/round first
- scored experiment commits should only touch the writable skill surface, or the scope guard will reject them
- after adding a new seam, rerun the scored pack against the benchmark-maintenance commit as `--diff-ref` so the experiment commit is evaluated in isolation

## Control File

Use [`program.md`](./program.md) as the human-authored control file for an external autonomous loop.

It mirrors the original `autoresearch` pattern:

- branch-per-run
- baseline eval
- commit before each experiment
- keep/discard based on score and simplification wins
- periodic promotion from the fast pack to the full pack
