# TheWorkshop Skill Autoresearch

This file adapts the `autoresearch` outer-loop idea to improve `TheWorkshop` itself.

The target is **not** the entire repository.
The target is the **skill surface** that shapes agent behavior:

- `README.md`
- `SKILL.md`
- `references/prompting.md`
- `references/workflow.md`
- `references/templates.md`
- `.codex/agents/*.toml`

Do not modify core runtime scripts unless the human explicitly expands the writable scope.

## Setup

Before starting the experiment loop:

1. Agree on a branch name like `autoresearch/theworkshop-<date>`.
2. Create that branch from the current `main`.
3. Read these files for context:
   - `README.md`
   - `SKILL.md`
   - `references/prompting.md`
   - `references/workflow.md`
   - `references/templates.md`
   - `.codex/agents/*.toml`
4. Read the benchmark packs:
   - `autoresearch/benchmark-pack.fast.json`
   - `autoresearch/benchmark-pack.full.json`
5. Create the results file by running a baseline eval:

```bash
python3 scripts/skill_autoresearch_eval.py \
  --pack autoresearch/benchmark-pack.fast.json \
  --diff-ref HEAD \
  --results-tsv state/autoresearch/results.tsv \
  --description "baseline"
```

The baseline should be evaluated with `--diff-ref HEAD` so scope enforcement sees zero changed files.

## What You Can Change

- tighten or simplify `SKILL.md`
- improve operator-facing guidance in `references/prompting.md`
- improve planning templates in `references/templates.md`
- improve repo-local agent instructions in `.codex/agents/*.toml`
- make corresponding documentation-truth updates inside the allowed surface when needed

## What You Cannot Change

- runtime scripts outside the allowed surface
- benchmark packs
- evaluator logic in `scripts/skill_autoresearch_eval.py`

If you believe a script change is required, stop and ask the human to widen the writable scope.

## Goal

Increase the evaluator score while keeping the skill simpler, clearer, and more truthful.

The score is not the only criterion:

- a tie with a simpler, more coherent diff can still be a win
- a small score increase that adds obvious prompt bloat is usually not a win
- documentation truth and constraint clarity matter more than clever wording

## Experiment Loop

Loop indefinitely until the human stops you:

1. Inspect the current branch and latest kept score in `state/autoresearch/results.tsv`.
2. Make one bounded experiment inside the allowed surface.
3. Commit the experiment.
4. Run the fast pack:

```bash
python3 scripts/skill_autoresearch_eval.py \
  --pack autoresearch/benchmark-pack.fast.json \
  --diff-ref HEAD~1 \
  --results-tsv state/autoresearch/results.tsv \
  --description "<short experiment description>"
```

5. If the score improves, keep the commit.
6. If the score ties, keep it only when the change is materially simpler or clarifies an important behavioral boundary.
7. If the score regresses or scope enforcement fails, discard the commit with a non-destructive revert/reset strategy appropriate to the branch workflow.
8. Periodically, and always before declaring a candidate especially strong, run the full pack:

```bash
python3 scripts/skill_autoresearch_eval.py \
  --pack autoresearch/benchmark-pack.full.json \
  --diff-ref HEAD~1 \
  --results-tsv state/autoresearch/results.tsv \
  --description "<short experiment description> (full)"
```

## Heuristics

Prefer experiments like:

- remove duplicated or conflicting instructions
- make success hooks more objective
- improve agreement/verification/closeout wording
- sharpen delegation boundaries in repo-local agents
- reduce prompt ambiguity without adding boilerplate

Avoid experiments like:

- broad stylistic rewrites with no behavioral thesis
- adding verbose rules that restate existing rules
- changing multiple unrelated files without a single hypothesis

## Keep / Discard Rule

Keep only when the experiment is better on at least one of these axes without damaging the others:

- higher fast-pack score
- same score with meaningfully simpler or clearer guidance
- same fast-pack score and better full-pack score

If uncertain, prefer clarity and smaller diffs.
