# ADR 0009: One JSON envelope — `api_ok` / `api_error`

> **Doc status:** Active

**Date:** 2026-09-16 (records UID-018, 2026-08-27, and wave 0.1, 2026-09-08)
**Status:** Accepted
**Owners:** `agent-backend` · `agent-uiux`

## Context

Every page used to invent its own failure UI because every route invented its
own failure body: `{error}`, `{success: false, message}`, `{status: 'error'}`,
bare strings, and HTML error pages on `/api` paths. The SPAs could not share
an error component, the desktop companion could not map a failure to anything
typed, and a 500 sometimes came back as a Jinja page.

## Decision

**Every JSON route replies through `api_ok` / `api_error`
(`oneirodex/utils/api_response.py`), and nothing else.**

```
success:  { ok: true,  success: true,  ...payload }
failure:  { ok: false, success: false, error: <human string>,
            error_code: <ERROR_CODES key>, detail?: <anything safe to show> }
```

- `error_code` is one of `ERROR_CODES` (`bad_request` 400, `unauthorized`
  401, `forbidden` 403, `not_found` 404, `conflict` 409, `unprocessable` 422,
  `payload_too_large` 413, `rate_limited` 429, `internal` 500, `bad_gateway`
  502, `unavailable` 503, …). The status code is derived from it, not chosen
  separately.
- `detail` is **passed to the browser as given** — no secrets, tokens, raw
  `.env` values or filesystem paths, ever. Validation errors (ADR 0010) put
  `{field: message}` there.
- A global error handler makes unhandled exceptions on `/api/**` and
  `/admin/api/**` answer with the envelope too; non-API paths still get HTML.
- `success` and `error` are kept alongside `ok` / `error_code` so classic
  theme JS that reads `data.success` / `data.error` keeps working through a
  deploy → Reset Themes window.
- **Eleven sites stay off the helper on purpose** — `/pulse`, batch `ok`,
  `ollama_status`, hardlink preview, game-details play status, the OIDC
  report — because wrapping them would lie or strip fields.
  `docs/dev/api-envelope-keeps.md` names each with its reason, and
  `scripts/api_envelope_lint.py` ratchets the count at **11** (from 1194).

`@oneirodex/api-client` models the envelope (`ApiOk<T>`, `ApiErrorEnvelope`,
`OneirodexApiError.error_code`) and `@oneirodex/ui`'s `errorFromResponse` /
`errorFromBody` turn it into the one shape pages catch (ADR 0005).

## Consequences

| Pros | Cons |
| --- | --- |
| One error component; one error type across SPAs and the companion | Two redundant keys (`ok`/`success`, `error`/`error_code`) until classic JS is gone |
| A new route cannot invent a body shape without moving the ratchet | The 11 keeps need a reason each time someone asks "why not wrap it" |
| Unhandled exceptions never leak a Jinja page onto an API path | — |

## Related

- ADR 0005 · ADR 0010
- `docs/dev/api-envelope-keeps.md`
