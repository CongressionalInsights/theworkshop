You are executing job `WI-20260214-001` in TheWorkshop sample project.

Objective:
- Draft a concise brief to `outputs/primary.md`.

Required outputs:
- `outputs/primary.md`
- `artifacts/verification.md`

Acceptance criteria:
- `outputs/primary.md` exists and is non-empty.
- `outputs/primary.md` contains `<promise>WI-20260214-001-DONE</promise>`.
- `artifacts/verification.md` exists and notes the verification checks performed.

Verification:
- Confirm both declared files exist and are non-empty.
- Run `scripts/plan_check.py` at project root.
- Record results in `artifacts/verification.md`.

Only emit this completion promise when everything above is objectively true:
<promise>WI-20260214-001-DONE</promise>
