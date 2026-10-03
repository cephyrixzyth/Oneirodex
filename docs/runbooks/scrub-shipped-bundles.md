# Scrub shipped bundles (SCRUB-7)

> **Doc status:** Active

Before publishing a Docker image or release tag, confirm Class A / competitive tokens do **not** leak into built SPA assets.

## Rebuild static dist

Source scrub alone is not enough — stale `static/dist/**` can still ship competitor strings.

```bash
# From repo root — one workspace install, then rebuild member + admin SPAs into static/dist
npm ci
npm run build --workspace=member-app
npm run build --workspace=admin-app   # if present / used in image
```

Commit or copy rebuilt assets into the image build context as your release process requires. Do not publish an image whose `static/dist` predates the last scrub of `frontend/*/src`.

## Grep built bundles against private banned list

Maintain patterns in the gitignored vault (`docs/_private/security/banned-tokens.txt`). **Never** paste Class A tokens into public docs or CI logs.

```bash
# From repo root (requires local private list)
rg -i -f docs/_private/security/banned-tokens.txt static/dist \
  --glob '!docs/_private/**'

# Optional: also scan image layer extract or desktop web assets
# rg -i -f docs/_private/security/banned-tokens.txt path/to/extracted/ui
```

Empty match set = pass. Any hit → rebuild from scrubbed source, re-grep, then publish.

## Related

- Policy: SCRUB-7 (local strategy notes).
- Release SOP: [release-checklist.md](release-checklist.md)
