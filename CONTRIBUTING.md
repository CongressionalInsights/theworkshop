# Contributing to TheWorkshop

Thanks for contributing.

## Scope

In scope:

- Reliability improvements to planning/gating/orchestration
- Dashboard and monitoring improvements
- Documentation and examples
- Test coverage improvements

Out of scope (for this repo):

- Productized hosted service features
- Private consulting workflows
- Large unrelated framework migrations

## Contribution Quality Bar

Every PR should include:

1. Clear problem statement and expected behavior
2. Focused change scope
3. Tests updated/added when behavior changes
4. Docs updated when interface or workflow changes
5. Notes on compatibility/backward behavior when relevant

## Pull Request Checklist

- [ ] I linked the issue (or explained why none exists)
- [ ] I added/updated tests for non-trivial changes
- [ ] I updated docs (`README`, `references/*`, templates) as needed
- [ ] I described risk and rollback plan for risky changes

## Issue Triage Labels

Maintainers use one `type:*` + one `status:*` label:

- `type:bug`, `type:enhancement`, `docs`
- `status:needs-repro`, `status:accepted`, `status:out-of-scope`

## Development Notes

Run checks from `scripts/`:

```bash
cd scripts
for t in *_test.py; do python3 "$t"; done
```

For release prep, use `RELEASE_CHECKLIST.md`.
