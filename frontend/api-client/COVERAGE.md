# `@oneirodex/api-client` endpoint coverage

> **Doc status:** Reference

What the typed client wraps today, and what a SPA adopting it in Phase 3
(Track B) will have to add. "Covered" means a `create<Name>Api` module with at
least a happy-path + error-path test; "partial" means some verbs of a group are
wrapped; "TODO" means no wrapper yet — call it through `client.request<T>(path,
init)` directly, or add a module.

The client models the real response envelope (`ok` / `error` / `error_code` /
`detail` / `message`) — see `src/types.ts` (`ApiErrorEnvelope`, `ApiOk<T>`,
`isApiError`) and `OneirodexApiError` (`.status`, `.error_code`, `.body`).

## Transports

| Transport        | Factory                                                   | Auth                                                                                                         | Use                                 |
| ---------------- | --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ | ----------------------------------- |
| Bearer (default) | `createRequester` / `createOneirodexClient`               | `Authorization: Bearer gt_…` via `getToken`                                                                  | desktop companion, thin client      |
| Browser          | `createBrowserRequester` / `createOneirodexBrowserClient` | session cookie + `X-CSRFToken` (`credentials: 'include'`, `csrfToken()` injected), `onUnauthorized()` on 401 | member / admin / ops SPAs (Phase 3) |

`createOneirodexBrowserClient(config)` builds the same resource groups as
`createOneirodexClient` over the browser transport — the composed client the
SPAs adopt (ops-glance `src/api/summary.ts` is the first, Phase 3.3).

## Resource modules

| Group                | Module         | Status  | Methods                                                                                                                                                                                                                                                       | Notes                                                                                           |
| -------------------- | -------------- | ------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| Tokens               | `tokens`       | covered | `list`, `create`, `revoke`                                                                                                                                                                                                                                    | `/api/tokens`                                                                                   |
| Playtime             | `playtime`     | covered | `startSession`, `heartbeatSession`, `stopSession`, `me`                                                                                                                                                                                                       | member `api/playtime.ts` sits on it                                                             |
| Browse / search      | `browse`       | partial | `search`, `listCollections`                                                                                                                                                                                                                                   | search filters/facets not modelled                                                              |
| Updates              | `updates`      | covered | `inbox`, `scan`, `storeSearch`, `addWanted`                                                                                                                                                                                                                   | member `api/updates.ts` sits on it; `/api/acquire/*` is a different surface, still raw          |
| Downloads            | `downloads`    | covered | `initiateGameDownload`, `listGameVersions`                                                                                                                                                                                                                    | Bearer + `write:download`                                                                       |
| Device / presence    | `device`       | covered | `heartbeat`, `capabilities`, `ackCommands`, `nackCommands`                                                                                                                                                                                                    | companion command transport                                                                     |
| Library              | `library`      | covered | `list`, `get`, `getWatch`, `setWatch`, `reorder`, `startScan`, `batchScan`, `batchEdit`, `refreshAll`, `getScanJobsStatus`                                                                                                                                    | scan management added PR-4c; batch delete not called by any SPA yet, still TODO                 |
| Library tools        | `libraryTools` | covered | `proposeLeafLibraries`, `importLeafLibrariesPreview`                                                                                                                                                                                                          | preview-only, never creates; create/scan live in the admin app's dedicated API adapter          |
| Game details         | `game`         | covered | `details`, `moreFrom`, `editions`, `screenshots`                                                                                                                                                                                                              | freshness, saves, mods, cheats TODO                                                             |
| Achievements         | `achievements` | covered | `forGame`, `me`, `setUsername`                                                                                                                                                                                                                                | RetroAchievements, read-only; admin match/status stay on `adminApi`                             |
| Save states          | `saves`        | covered | `list`, `remove`                                                                                                                                                                                                                                              | upload is multipart from the play shell's bridge, not wrapped; member `api/saves.ts` sits on it |
| Collections          | `collections`  | covered | `list`, `create`, `get`, `update`, `remove`, `addItem`, `removeItem`, `reorderItems`                                                                                                                                                                          | full CRUD                                                                                       |
| Discover             | `discover`     | covered | `sections`, `row`, `zone`, `genreHub`, `getPins`, `setPins`                                                                                                                                                                                                   |                                                                                                 |
| Account              | `account`      | covered | `summary`, `changePassword`, `uploadAvatar`, `setStockAvatar`, `listInvites`, `createInvite`, `deleteInvite`                                                                                                                                                  | multipart `FormData` upload, no forced `Content-Type`; full account surface wrapped             |
| Wishlist / favorites | `wishlist`     | covered | `listRequests` (+`all`), `createRequest`, `cancelRequest`, `resolveRequest`, `setBatch`, `listFavorites` (+`name`, `itemKind`), `checkFavorite`, `toggleFavorite`                                                                                             | member `api/wishlist.ts` + `api/favorites.ts` sit on it                                         |
| Ops summary          | `ops`          | covered | `getSummary`, `getSystemDetail`, `getLogs`                                                                                                                                                                                                                    | `system`/`logs` GETs added PR-4c; loose response shapes (every section nullable)                |
| Admin users          | `adminUsers`   | covered | `list`, `upsert`, `listInviteQuotas`                                                                                                                                                                                                                          | `/admin/api/users`, `/admin/api/user/{id}` (id `0` = create), `/admin/api/invites` — admin only |
| Admin art            | `adminArt`     | covered | `preview`, `generate`, `apply`, `batchGenerate`, `getStockCatalog`, `generateStock`, `getSystemMarks`, `generateSystemMarks`, `getSystemMarksLab`, `searchCovers`, `applyCover`, `batchSearchCovers`, `batchApplyCovers`, `generateArtwork`, `downloadImages` | Art Studio + provider covers + AI artwork + bulk image downloads, all under `/admin/api/**`     |

## Not yet wrapped (call `client.request` directly)

Chat / social (`/api/chat/**`), notifications, ownership imports
(`/api/ownership/**`), game servers, emulator profiles / BIOS / cheats,
layouts, quality profiles, providers / metadata search, AI triage, activity /
events SSE, RTC tokens, and the classic-form admin surfaces that are not JSON
APIs (`/admin/themes/reset`). `/admin/library/add` is a React route; create and
scan actions call the dedicated admin-app API adapter.

Types are intentionally loose (`[key: string]: unknown` with the known fields
typed) matching the `src/types.ts` house style — tighten per group as
`docs/openapi/openapi.json` schemas expand.

## Follow-ups

- `docs/openapi/openapi.json` regen was out of scope for wave C3.7-client — the
  new groups above are not yet in the spec.
- **admin-app browser-transport adoption — done (PR-4c).** `admin-app/src/api/adminApi.ts`
  now sits on `createBrowserRequester` instead of its own hand-rolled `fetch`
  verbs; exported names (`getJson`/`postJson`/`postJsonResult`/`putJson`/`deleteJson`/
  `adminError`/`csrfToken`/`csrfHeaders`) are unchanged so call sites did not move.
  That required two admin vitest mock fixes across ~25 test files: a
  `content-type: application/json` response header (`unwrapResponse` returns
  `undefined` without one) and a `.text()` method alongside `.json()`
  (`unwrapResponse`'s error path reads the body via `response.text()`, not
  `.json()`, which the old hand-rolled `adminApi` never called). The new
  `adminUsers` / `libraryTools` / `adminArt` modules above, plus the scan-management
  additions to `library`, cover the `/admin/api/**` and `/api/admin/**` surface
  admin-app actually calls — none of admin-app's own hooks/components were
  rewired onto them yet (still call `getJson`/`postJson`/`postJsonResult`
  directly); that adoption is a separate follow-up.
- **member-app browser-transport adoption — done (PR-6 remainder).** `member-app/src/api/client.ts`
  sits on `createBrowserRequester` with `getJson` / `postJson` / `putJson` /
  `patchJson` / `deleteJson` plus `send` (FormData / body-less POST) and
  `sendResult` (4xx without throw). Every `src/api/` JSON wrapper uses those
  verbs. Preferences now uses shared `GET` / `PUT /api/account/preferences`
  and `EventSource` streams remain off this path. Chat / voice / space-rail / PC cheats / related
  media / loading-icon / the library-scan toast poll now use the same verbs.
  Vitest mocks need `content-type: application/json` and `.text()` for the
  same reason admin did.
- **member collections typed module — done.** `member-app/src/api/collections.ts`
  CRUD verbs call `createCollectionsApi` through `memberResource` (same
  requester as `getJson`, not a second `createOneirodexBrowserClient`) and
  `withMemberError` so pages still catch `errorFromBody`. Exported names and
  camelCase args (`isPublic`) are unchanged. `searchGames` stays on
  `getJson /api/search` — browse search is a different group (`createBrowseApi`)
  and the live `/api/search` body is a JSON array, not the typed
  `SearchResponse` object. Next group to rewire: pick another covered module
  from the table above; admin-app hooks are still on `getJson`/`postJson`.
- Account `uploadAvatar` — done (this PR). Moved from `@oneirodex/ui`'s
  `accountApi.ts` (PR-4 sub-wave d) into `account.ts` here as a multipart
  `FormData` POST; `AccountModal.tsx` now calls it through a scoped
  `createOneirodexBrowserClient` instance instead of the removed hand-rolled
  helper. Account group status is now covered end to end.
