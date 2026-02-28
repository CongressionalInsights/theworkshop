# Lessons Learned

Lessons are first-class operating data in TheWorkshop.

## Storage

Project-local (always):
- `notes/lessons-learned.md` (append-only narrative log)
- `notes/lessons-index.json` (generated index; query-friendly)

Optional global library (opt-in):
- `$CODEX_HOME/skills/theworkshop/state/global-lessons.jsonl`

Scripts:
- capture: `scripts/lessons_capture.py`
- query: `scripts/lessons_query.py`
- apply: `scripts/lessons_apply.py`

## Capture Contract

Each captured lesson should include:
- context (what happened)
- what worked
- what failed
- recommendation (what to do next time)
- tags (comma-separated)
- linked IDs (`WI-*`, `WS-*`, `PJ-*`)

Minimum quality bar:
- capture reusable operating guidance (patterns, pitfalls, verification tactics)
- avoid one-off noise (temporary typo fixes, trivial retries, obvious mechanical errors)

## Retrieval Timing and Placement

Retrieve relevant lessons at job start, before significant execution.

Default behavior:
- `job_start.py` automatically runs lessons application unless `--no-apply-lessons` is provided.
- Control knobs:
  - `--lessons-limit N`
  - `--lessons-include-global`

Insertion point in job plan:
- `# Relevant Lessons Learned`

Application policy:
- If the section is empty/placeholder, replace it with ranked lessons.
- If the section already contains non-placeholder text, append non-duplicate lessons only.

## Relevance Ranking Inputs

Recommended ranking signals:
- job title / objective similarity
- workstream context
- tag overlap
- linked-ID overlap
- recency

Current scripted ranking (`lessons_query.py`) is deterministic and combines:
- text phrase/token match over snippet + context/worked/failed/recommendation
- tag overlap
- linked-ID overlap (`WI-*`, `WS-*`, `PJ-*`)
- recency from `captured_at` (or lesson ID date fallback)
- deterministic tie-breakers (score, overlap counts, recency, lesson ID)

## Guardrails

Do not store secrets or sensitive data in lessons.

Never include:
- API keys, passwords, tokens, private credentials
- personal data not required for execution
- raw secret-bearing logs

If sensitive text appears in context, summarize safely before capture.
