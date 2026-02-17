# Release Checklist (`v0.1.0` Baseline)

## 1. Package Hygiene

- [ ] Confirm source-of-truth layout only (`scripts/`, `references/`, `examples/`, docs assets, root docs)
- [ ] Ensure local run artifacts are ignored (`PJ-*`, `outputs/`, temp/log state)
- [ ] Verify architecture image exists at `docs/assets/theworkshop-systems-architecture.png`

## 2. Documentation Truth

- [ ] `README.md` has install, quickstart, architecture diagram, gates, roadmap
- [ ] `SKILL.md` remains runtime/operator contract
- [ ] `CHANGELOG.md` includes public launch baseline section
- [ ] `CONTRIBUTING.md`, `SECURITY.md`, `SUPPORT.md`, `CODE_OF_CONDUCT.md` are present

## 3. Test and Scenario Confidence

- [ ] Run `scripts/*_test.py`
- [ ] Run one synthetic end-to-end scenario and verify gates + dashboard artifacts
- [ ] Verify imagegen path via `OPENAI_KEY` -> `OPENAI_API_KEY` injection

## 4. GitHub Metadata + Triage Setup

Repository metadata (manual):

- Description: `Project OS for non-coding work with TruthGate, orchestration, monitoring, and spend visibility.`
- Topics: `codex-skill`, `workflow`, `project-os`, `automation`, `non-coding`
- Homepage: leave empty unless docs site is live

Create triage labels:

```bash
gh label create "status:needs-repro" --color C5DEF5 --description "Needs reproducible steps" || true
gh label create "status:accepted" --color 0E8A16 --description "Accepted into roadmap" || true
gh label create "status:out-of-scope" --color BFDADC --description "Outside project scope" || true
gh label create "type:bug" --color D73A4A --description "Bug report" || true
gh label create "type:enhancement" --color A2EEEF --description "Enhancement request" || true
gh label create "docs" --color 0075CA --description "Documentation" || true
```

## 5. Release + Share Flow

- [ ] Tag and publish `v0.1.0`
- [ ] Use `releases/v0.1.0.md` for release notes body
- [ ] Open pinned Discussion: `Start here: adoption feedback + Q&A`
- [ ] Open one issue: `Known limitations`
- [ ] Share canonical URL as release page link
