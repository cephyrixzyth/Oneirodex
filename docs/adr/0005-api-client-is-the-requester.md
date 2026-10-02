# ADR 0005: `@oneirodex/api-client` is the one requester

> **Doc status:** Active

**Date:** 2026-09-09
**Status:** Accepted
**Supersedes:** [ADR 0002](0002-defer-api-client-spa.md) (deferred SPA adoption)
**Owners:** `agent-desktop` · `agent-backend` · `agent-uiux`

## Context

ADR 0002 deferred wiring `@oneirodex/api-client` into the member SPA until after
1.0, to avoid a mid-polish cutover. 1.0.0-beta has shipped and two things have
changed since:

- **The envelope is now real.** Every route replies through `api_ok` /
  `api_error` (`oneirodex/utils/api_response.py`): `{ ok, error, error_code,
  detail?, message?, success }`. The client did not model it —
  `OneirodexApiError` read only `body.error` and ignored `error_code`, and the
  success envelope was untyped. The SPAs each hand-roll their own `src/api/`
  fetch layer with no shared error contract, which is the exact problem the
  envelope was introduced to fix.
- **The client only served the desktop companion**, covering ~10 of ~50
  member endpoints with ~1 real test — too thin for a SPA to adopt as-is.

Wave C3.7-client closed the gap: the client now models `ApiErrorEnvelope` /
`ApiOk<T>` / `isApiError`, `OneirodexApiError` carries `.status` +
`.error_code`, a same-origin **browser transport** exists alongside the Bearer
one, and coverage grew to twelve resource groups (`COVERAGE.md`).

## Decision

**One typed client for the desktop companion and the React SPAs.**

- Two transports, one envelope model:
  - **Bearer** (`createRequester` / `createOneirodexClient`) — `Authorization:
    Bearer gt_…` via `getToken`. Desktop companion and thin client. Unchanged;
    stays the default.
  - **Browser** (`createBrowserRequester`) — session cookie, `credentials:
    'include'`, `X-CSRFToken` on mutations from an injected `csrfToken()`,
    `onUnauthorized()` on 401. For the member / admin / ops SPAs. The client
    never imports a SPA's token store — the getter is injected via config.
- **SPAs migrate their `src/api/` layers onto it in Phase 3 (Track B)**, one
  low-risk path at a time, not in a single cutover. `COVERAGE.md` records which
  groups are ready to adopt and which Track B must still extend.
- Types stay loose (`[key: string]: unknown` with known fields typed) until
  `docs/openapi/openapi.json` schemas expand; regen for the new groups is a
  tracked follow-up.

## Consequences

| Pros | Cons |
| --- | --- |
| One error contract (`error_code`) across desktop + SPAs; a shared error component becomes possible | Two transports to keep behaviourally aligned (shared `unwrapResponse` tail mitigates) |
| SPA `fetch` boilerplate and ad-hoc error handling retire path-by-path | Phase 3 migration is real work spread across three SPAs |
| The client is exercised by SPA traffic, not just the companion | `openapi.json` and the client can drift until schemas are regenerated |
| Desktop behaviour is unchanged — Bearer transport is untouched | — |

## Related

- [ADR 0002](0002-defer-api-client-spa.md) — superseded
- `frontend/api-client/COVERAGE.md` — endpoint group status
- `oneirodex/utils/api_response.py` — the envelope
