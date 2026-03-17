# Docs Assets

Public docs imagery for TheWorkshop is generated from a tracked prompt manifest rather than hand-authored SVG placeholders.

Source of truth:

- `docs/assets/prompts.jsonl`
- `python3 scripts/generate_docs_assets.py`

Current generated outputs:

- `docs/assets/theworkshop-mark.png`
- `docs/assets/theworkshop-systems-architecture.png`
- `docs/assets/subagents-explainer-preview.png`

Regenerate all assets:

```bash
python3 scripts/generate_docs_assets.py --force
```

Regenerate a single asset:

```bash
python3 scripts/generate_docs_assets.py --asset theworkshop-mark --force
```

Credential handling follows the existing optional imagegen adapter rules already documented by TheWorkshop:

- `gpt-image-1.5` is the default docs-asset model
- env-first for `THEWORKSHOP_IMAGEGEN_API_KEY`
- compatibility aliases for `OPENAI_API_KEY` / `OPENAI_KEY`
- keychain fallback through the `apple-keychain` skill when env credentials are absent

Public docs should reference the generated PNG outputs, not local draft vectors.
