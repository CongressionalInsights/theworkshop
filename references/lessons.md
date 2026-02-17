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

Insertion point in job plan:
- `# Relevant Lessons Learned`

The section should summarize the top relevant lessons and how they will be applied in the current job.

## Relevance Ranking Inputs

Recommended ranking signals:
- job title / objective similarity
- workstream context
- tag overlap
- linked-ID overlap
- recency

Current scripted query behavior (`lessons_query.py`) ranks primarily by snippet/query token match and tag overlap, with optional global-library inclusion.

## Guardrails

Do not store secrets or sensitive data in lessons.

Never include:
- API keys, passwords, tokens, private credentials
- personal data not required for execution
- raw secret-bearing logs

If sensitive text appears in context, summarize safely before capture.
