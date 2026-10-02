# ADR 0010: Request validation with pydantic `@validate_body`

> **Doc status:** Active

**Date:** 2026-09-16 (records wave A2.4, 2026-09-09, and PRs #81–#101, 2026-09-11/12)
**Status:** Accepted
**Owners:** `agent-backend`

## Context

~150 routes read `request.get_json()` and hand-rolled the same three checks —
is it an object, is the field present, is it the right type — each with its
own wording and its own status code (mostly 400, sometimes 404 or 500 when a
missing key reached the ORM). The shape of a request body lived in the view
and nowhere a client could read it.

## Decision

**Declare request bodies as pydantic v2 models under `oneirodex/schemas/`,
one module per route surface, and wrap the view with
`@validate_body(Model)` (`oneirodex/utils/validation.py`).**

- The decorator sits **innermost** (after auth), parses the JSON object,
  validates it, and passes the model as `body=`. Failure is
  `422 unprocessable` through the envelope (ADR 0009) with `detail` =
  `{field: message}` — secrets and paths stripped.
- **`model_config = ConfigDict(extra='forbid')` on every model** unless a
  route genuinely accepts pass-through keys. An unknown key is a client bug
  worth a 422, not silence. Models are sized to accept exactly what the
  hand-rolled checks accepted; each docstring names the guard it replaced and
  which optional fields exist for which caller (`client` for theme-JS
  playtime, untyped `image_id` because theme JS posts a number or a string).
- **Semantic checks stay in the view** — does the game exist, is the caller
  an admin, is the status transition legal. The model covers shape, type and
  presence only. So a well-formed body can still get 400/403/404 from the
  view, and those codes did not move.
- `@validate_batch_body` is the partial-success variant: same 422, plus
  `updated` / `skipped` / `errors` / `limit` so a batch bar never goes blank.
- `scripts/get_json_lint.py` ratchets the remaining `request.get_json` sites
  (**103** at the time of writing); `docs/dev/pydantic-adoption.md` holds the
  per-file order and the rule: **one file per commit, never a sweep.**

**Compatibility stance, stated plainly.** `extra='forbid'` is strictly
narrower than the guards it replaced. That is safe today — every theme-JS
body, every SPA API layer, and the companion's `lifecycle` post were checked
against their models (v1 cycle Phase 1, F11) — but it means a client that
adds a field before the server knows it gets a 422, and two client surfaces
here lag the image: the **installed desktop companion** and **theme JS served
from the library volume** (updates only on Reset Themes). Adding a field is
therefore a server-first change, and a model must never lose a field a
shipped client sends.

## Consequences

| Pros | Cons |
| --- | --- |
| One 422 contract, machine-readable `detail`, one place to read a body's shape | Version skew now fails loudly instead of being ignored — server-first ordering is a rule to remember |
| Hand-rolled guards and their inconsistent codes retire file by file | 103 sites still to migrate; each needs its callers read, not just its guard |
| Models are the seed for OpenAPI request schemas | pydantic pins its core (`pydantic-core==2.46.5`); drift on a shared interpreter breaks import (pinned explicitly since PR #113) |

## Related

- ADR 0009 · `docs/dev/pydantic-adoption.md` · `oneirodex/schemas/__init__.py`
