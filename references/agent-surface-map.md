# Agent Surface Map

TheWorkshop uses a shared/global runtime layer plus four project-local layers for agent behavior. Keep them aligned and avoid treating the same concept as authoritative in multiple places.

## 0. Shared global agent library

Location:
- `~/.codex/agents/*.toml`

Authority:
- Cross-repo reusable subagent roles that are narrow, stable, and mostly read-heavy.

Examples:
- `explorer`
- `reviewer`
- `docs_researcher`
- `test_triager`
- `security_reviewer`
- `monitor`

Use this layer for:
- stable cross-repo agent behavior
- generic read-heavy helper roles

Do not encode repo-specific workflow policy here.

## 1. Runtime agent definitions

Location:
- `.codex/agents/*.toml`

Authority:
- Canonical executable Codex agent definitions for repo-scoped subagent behavior.

Examples:
- `theworkshop_explorer`
- `theworkshop_worker`
- `theworkshop_reviewer`
- `theworkshop_memory_curator`
- `theworkshop_lessons_curator`
- `theworkshop_loop_worker`

Use this layer for:
- model selection
- reasoning effort
- sandbox defaults
- narrow behavioral instructions
- display nicknames
- repo-scoped memory/lesson promotion rules

## 2. Runtime limits and project-scoped config

Location:
- `.codex/config.toml`

Authority:
- Canonical repo-scoped runtime settings for agent execution.

Use this layer for:
- `[agents].max_threads`
- `[agents].max_depth`
- `[agents].job_max_runtime_seconds`

Keep broad feature toggles and user-wide defaults in `~/.codex/config.toml` unless the behavior is project-specific.

## 3. Planning metadata registry

Location:
- `references/agents/*.json`

Authority:
- Canonical planning metadata for orchestration, retry/budget defaults, and compatibility mapping.

Use this layer for:
- orchestration-oriented role metadata
- legacy aliases
- fallback built-in agent type
- dispatch budget and retry defaults

Do not treat this layer as the executable runtime definition.

## 4. Derived job frontmatter

Location:
- job `plan.md` frontmatter

Authority:
- Compatibility and job-local override surface.

Fields:
- `agent_profile`
- `dispatch_budget`
- `retry_limit`

Rules:
- `agent_profile` is the canonical job-local selector for new plans and ongoing workflows.
- `dispatch_budget` and `retry_limit` may be written into frontmatter to preserve per-job decisions.
- `agent_type_hint` is historical only and should not be emitted by active workflows.
- Existing plans should be normalized with `scripts/normalize_agent_profiles.py`.

## Resolution order

`resolve_agent_profile.py` resolves agent behavior in this order:
1. explicit `agent_profile` in job frontmatter
2. `orchestration_mode`
3. `stakes`
5. registry fallback

The resolver outputs:
- canonical planning profile name
- canonical runtime agent name
- built-in fallback agent type

`dispatch_orchestration.py` should treat that resolver output as the canonical bridge between plan metadata and runtime telemetry.

## Memory and lessons

- Shared/global agents may read memory but should not write durable memory directly.
- Repo-local worker/reviewer/explorer agents may stage memory and lesson candidates only.
- Repo-local curator agents are the preferred promotion path for:
  - `.theworkshop/memory-proposals/*.json`
  - `.theworkshop/lessons-candidates/*.json`
- Loop workers should stage learning during attempts and promote only after terminal loop state.
