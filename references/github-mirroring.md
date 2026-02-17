# GitHub Mirroring (Opt-In)

TheWorkshop can mirror local project state into GitHub using `scripts/github_sync.py`.
Local plans remain the control plane; GitHub is a synchronized external view.

## Opt-In Prerequisites

Required before sync:
- project frontmatter includes `github_enabled: true`
- project frontmatter includes or resolves `github_repo: owner/repo`
- `gh` CLI is installed and authenticated (`gh auth status`)

If `github_repo` is not set, the sync script attempts to detect it from the local git remote.

## Enable Flow

Enable for a project:

```bash
python3 scripts/github_sync.py --project /path/to/project --repo owner/repo --enable
```

Once enabled, subsequent syncs can omit `--enable`.

## Mapping Rules

Default mappings from local model to GitHub:
- **Job (WI) -> Issue**
  - title format: `[WI-...] <job title>`
- **Workstream -> Label**
  - `ws:<slug>`
- **Status -> Label**
  - `status:planned|in_progress|blocked|done|cancelled`
- **Wave -> Milestone**
  - from project `waves` frontmatter
- **Project board (optional)**
  - best-effort when `--with-project-board` is provided

## Idempotency Map

Sync state is stored in:
- `notes/github-map.json`
- schema: `theworkshop.githubmap.v1`

This file tracks issue/milestone mappings and last sync time to keep sync idempotent.

## Sync Behavior

On sync run, `scripts/github_sync.py` performs:
1. ensure required labels exist
2. ensure milestones exist for configured waves
3. ensure WI issues exist (or recover existing issues by title search)
4. update issue body/labels/milestone to match local plan state
5. close issue when local job status is `done`
6. write back `github_issue_number` and `github_issue_url` to each job plan
7. update `notes/github-map.json` (`last_sync_at`, mappings)

## Dry Run Behavior

Use `--dry-run` to avoid issue/milestone mutation:

```bash
python3 scripts/github_sync.py --project /path/to/project --dry-run
```

Important caveats from current behavior:
- label ensuring still runs
- project board creation may still run when `--with-project-board` is also used

## Failure Modes and Recovery

Common failures:
- missing repo (`--repo` not provided and detection fails)
- GitHub auth unavailable/expired
- GitHub API/network errors

Recovery:
- set explicit repo: `--repo owner/repo`
- re-authenticate: `gh auth login`
- rerun sync; idempotency map and WI title recovery reduce duplicate creation risk

## Dispatcher Shortcut

Equivalent dispatcher command:

```bash
python3 scripts/theworkshop github-sync --project /path/to/project --enable --repo owner/repo
```
