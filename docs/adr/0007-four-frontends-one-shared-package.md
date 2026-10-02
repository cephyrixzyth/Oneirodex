# ADR 0007: Three React SPAs, one shared package, a Jinja hybrid underneath

> **Doc status:** Active

**Date:** 2026-09-16 (records decisions taken 2026-07 → 2026-09-11)
**Status:** Accepted
**Owners:** `agent-uiux` · `agent-backend` · `agent-docs`

## Context

The product has three audiences with different chrome: the household member
(browse, play, social), the operator (libraries, scans, users, ops), and an
at-a-glance ops pulse meant for a wall display. The pre-1.0 codebase had one
member SPA and ~47 Jinja admin pages that had grown their own CSS, JS and
failure UI each — the "inconsistent feel across pages" the human kept
reporting (UID-017, UID-018).

A big-bang admin rewrite was explicitly rejected in `v1-readiness.md`
("Progressive hybrid — React chrome + Jinja bodies until parity").

## Decision

**Three Vite/React SPAs plus one shared package, each a TypeScript
`strict: true` workspace, over a Flask that still renders Jinja bodies where
React has not reached yet.**

| Package | Role | Where it mounts |
| --- | --- | --- |
| `frontend/member-app` | Household SPA | `/library`, `/discover`, `/play/…`, social, Big Picture |
| `frontend/admin-app` | Operator SPA — shell, dashboard, Ops board, users, invites, support, integrations hub, Libraries, Scan jobs | `/admin/**`; a page kind with `hasLegacyBody` falls back to the Jinja body |
| `frontend/ops-glance` | Ops pulse widgets | embedded in the admin Ops board and a static entry |
| `frontend/shared` (`@oneirodex/ui`) | Chrome + contracts every SPA needs: `PageStatus`, `confirmDialog`, toast stack, CSRF lookup, `errorFromResponse`, `ViewerProvider` / `ShellConfigProvider`, `<Button>`, `useResource` (react-query) | imported by all three |

Rules that fell out of the debt log and are now load-bearing:

- **One failure UI.** Pages render `PageStatus` for load/empty/error; errors
  come from the API envelope (ADR 0009), never a per-page string.
- **One token layer.** All colour, radius and type come from `--od-*` custom
  properties (`od-tokens.css`); `scripts/css-token-lint.mjs` ratchets raw
  literals in CSS, JSX inline styles and JS data constants to **0**, across
  `.css/.js/.jsx/.ts/.tsx`.
- **One button language.** `.od-btn` / `.od-cbtn` / `.od-seg__item` share a
  font-relative box; `buttonLanguage.test.js` and the `<Button>` primitive
  keep new sites honest.
- **The admin hybrid is supported, not transitional debt.** Remaining Jinja
  bodies (themes, OIDC fields, newsletter, recognition) migrate page by page;
  a React page kind and its legacy body must not both own the same DOM.
- **Bundles are baked into the image** (`oneirodex/static/dist/*` from the
  Dockerfile's `frontend-build` stage); theme CSS/JS is *not* — it ships from
  the library volume and updates only on Reset Themes (`docs/admin/themes-reset.md`).

## Consequences

| Pros | Cons |
| --- | --- |
| Member, admin and ops share chrome, contracts and tests; a fix in `@oneirodex/ui` lands everywhere | Three apps to build, typecheck and test in CI (five vitest jobs) |
| Admin migrates incrementally with a visible fallback rather than a flag day | Two rendering worlds in admin for the foreseeable future; theme JS in the volume is versioned separately from the image |
| Strict TS in every workspace | Strictness is only as real as the `any` count — member-app's conversion left **878** `: any` sites (Phase 2 ratchets them down) |

## Related

- ADR 0005 — the one requester the SPAs adopt
- ADR 0008 — how the workspaces install
- `docs/strategy/admin-hybrid.md` (local) · `docs/dev/ui-debt-log.md`
