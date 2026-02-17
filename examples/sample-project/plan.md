---
schema: theworkshop.plan.v1
kind: project
id: PJ-20260214-001
title: "Sample Project"
status: planned
agreement_status: proposed
agreed_at: ""
agreed_notes: ""
started_at: "2026-02-14T00:00:00Z"
updated_at: "2026-02-14T00:00:00Z"
completed_at: ""
completion_promise: "PJ-20260214-001-DONE"
github_enabled: false
github_repo: ""
subagent_policy: auto
max_parallel_agents: 3
waves:
  - id: WV-20260214-001
    title: "Wave 1: Research"
    start: "2026-02-14"
    end: "2026-02-14"
workstreams:
  - WS-20260214-001
---

# Goal

Demonstrate a minimal but current TheWorkshop project with valid control-plane structure.

# Acceptance Criteria

- Project/workstream/job plans contain required frontmatter and stable headings.
- Sample WI includes declared outputs/evidence paths and reward/truth fields.
- `scripts/plan_check.py --project <sample-project>` passes structural checks.

# Workstreams

<!-- THEWORKSHOP:WORKSTREAM_TABLE_START -->
| Workstream | Status | Title | Depends On |
| --- | --- | --- | --- |
| WS-20260214-001 | planned | Research |  |
<!-- THEWORKSHOP:WORKSTREAM_TABLE_END -->

# Success Hook

- Acceptance criteria: see section above.
- Verification: run `scripts/plan_check.py` from this sample project root.
- Completion promise: `<promise>PJ-20260214-001-DONE</promise>`

# Progress Log

- 2026-02-14T00:00:00Z created sample project skeleton.

# Decisions

- 2026-02-14T00:00:00Z keep sample intentionally small and gate-oriented.

# Lessons Learned (Links)

- `notes/lessons-learned.md`

# Compatibility Notes

- schema: `theworkshop.plan.v1`
- headings in this file are stable anchors used by tooling.
