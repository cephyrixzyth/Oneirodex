# Architecture (maintainer map)

> **Doc status:** Active

Oneirodex dispatches HTTP requests through the FastAPI ASGI runtime, with three React SPAs and a typed HTTP client. Flask route modules remain as development-time compatibility and parity references; the runtime image no longer installs Flask or Jinja. This page is the map, not a rewrite of [ADR 0005](../adr/0005-api-client-is-the-requester.md) or [agent-locks.md](agent-locks.md).

The migration notes below are dated implementation checkpoints; their interim
runtime descriptions may be superseded by the current status above and in the
[Jinja/runtime inventory](admin-jinja-inventory.md).

**Current runtime acceptance (2026-10-14):** P17 removed Flask construction,
WSGI dispatch, and Flask/Jinja packages from the runtime image. Normal startup
creates `NativeRuntimeContext`; the current route census maps 730 legacy
method/path pairs to 716 FastAPI patterns and 14 ASGI handlers with no
unmatched paths. This is route inventory coverage, not proof of every
side-effect or browser state. P18's bounded UI, accessibility, and capture
evidence and exclusions are recorded in the
[private acceptance report](../_private/evidence/p18-ui-acceptance-2026-10-14.md).

The package root exposes legacy Flask objects lazily from
`oneirodex/legacy_app.py`; those exports are for the development compatibility
suite and require `requirements-dev.txt`. Normal startup creates
`NativeRuntimeContext`, registers framework-independent ORM models, and serves
through FastAPI. The native handlers preserve the signed-session, CSRF,
authorization, response, and side-effect contracts documented in the dated
route migration notes below. Production `requirements.txt` and the Docker
image exclude Flask, its extensions, and Jinja2; the development test harness
still installs Flask/Jinja so historical compatibility tests can run.

Native code that reuses a compatibility helper must handle Flask being absent,
not only an absent Flask application context. The 2026-10-15 local image check
caught this in the login password-timing helper, member lifecycle path, and
theme-font fallback. Those helpers now use framework-independent logic or
catch the missing optional import and use the configured runtime fallback;
`tests/test_native_runtime_framework_free.py` guards the boundary.

The ORM declarations share `ModelBase.metadata` across the native runtime and
development compatibility adapter. Alembic imports that framework-independent
metadata directly, so startup migration checks run in the production image
without importing Flask. `/pulse` is liveness; `/awake` is readiness and checks
database connectivity plus initialization. Route-count coverage records
registered method/path pairs; it is not a substitute for per-route behavior,
side-effect, or real-platform acceptance.

The dated implementation checkpoints below describe how the migration
progressed. Treat their interim statements about Flask startup, WSGI fallback,
route gaps, and dependency removal as historical whenever they conflict with
the current runtime status above.

Storage hardlink preview/apply now also dispatch through FastAPI with the
existing admin, CSRF, feature-flag, library-root path-safety, and audit behavior.
Tests exercise apply through a fake adapter, so verification does not create a
filesystem hardlink. Flask startup and framework dependency retirement remain
open.

The admin malware-scan action also dispatches natively with its configured-root
allowlist, admin and CSRF gates, and existing result status contract. Its tests
use a fake scanner; production scanning remains behind the explicit admin action.

The member free-game claim-assist mutation and admin cropped-library-image
preview now use the same native request boundary. The claim keeps ownership
work behind the scoped data adapter; the image preview transforms the uploaded
base64 image in memory and does not write an asset.

LiveKit token issuance also has a native FastAPI handler. It keeps the room
membership check, feature/configuration gates, child video restrictions, and
the existing signed-user identity; route tests use a fake mint adapter.

Native write handlers apply CSRF to browser-session requests and retain the
existing API-token authentication path.

The first-run setup shell pages, ordered `POST /api/setup/step` transition,
and classic HTML form POSTs (`/setup/submit` plus the five step URLs) now
dispatch through FastAPI with existing signed-session and CSRF compatibility.
Form field names are translated into the same validated transition contract;
the first-admin session handoff, step and admin gates, redirects, and flash
cookies are preserved. Setup seed helpers receive explicit configuration and
task-owner arguments without pushing a Flask application context. Other legacy
routes and the primary-runtime/dependency-retirement gates remain.

The Ops log, system, summary, device, and library-health reads also dispatch
through FastAPI with administrator and token-scope checks. Flask still registers
the compatibility URL map during startup, while FastAPI owns request dispatch.
Six retired admin bookmarks now use native FastAPI redirects with the original
admin/login checks and query forwarding: `/admin/library_tools`,
`/admin/scan_management`, `/admin/server_logs`, `/admin/system_logs`, and
`/admin/server_status_page`. Their targets remain the shared Help, Libraries &
scans, and Ops pages.
The classic `/admin/statistics/data` aggregate is also native and retains its
bare JSON payload alongside the newer `/api/admin/statistics` envelope.

Native route authentication now resolves signed session and remember-cookie
users through the shared fingerprint and active-user checks plus an injected
user lookup. Native dispatch no longer calls Flask-Login's user-loader hook.
Admin page GET/HEAD requests use the packaged FastAPI shell. The retired
`ONEIRODEX_NATIVE_ADMIN_PILOT` setting has no effect and is no longer passed
through Compose. Form writes use native compatibility handlers. The Docker
entrypoint requires the packaged shell bundle.

## Approved runtime migration

The approved target is FastAPI with compatibility for existing signed sessions,
static React page shells, and no Flask/Jinja2 dependency at final acceptance.
Normal startup now uses framework-independent config, native database setup,
and a `NativeRuntimeContext`; it no longer constructs Flask. FastAPI owns
registered route dispatch. The packaged admin shell is served by FastAPI and is
required by the container entrypoint. Member authentication and setup shells are served by the mounted
FastAPI auth/setup routers; the obsolete member-shell pilot flag and its second
Flask request-dispatch implementation have been removed. The member runtime
bootstrap resolves the existing signed session and issues compatible CSRF/session
cookies directly in FastAPI. Admin page requests use the shared signed
session resolver directly, while selected compatibility handlers still use the
shared `oneirodex/runtime_native/flask_compat.py` adapter for Flask request hooks,
session handling, redirects and response finalization. Admin auth also preserves remember
cookie and scoped Bearer-token precedence. FastAPI-native route and admin
bootstrap authentication now use the shared password-fingerprint resolver
directly, while Flask-Login remains available to the compatibility routes.
The single-game favorite and play-status APIs, admin library-platform
options, the member role/icon-pack/username endpoints, the release-calendar and quality-profile APIs, announcement reads and creation,
notification inbox/preferences actions, the admin notification-bus test action,
and personal API-token management use
request-local ORM sessions where needed and direct Starlette JSON responses; they no longer push Flask app
contexts. Their legacy response shapes, ACL, CSRF, and signed-session behavior
remain covered by route tests.
The admin challenge-solver and ambient-lighting status, config, and test routes
now handle authentication, authorization, response serialization, and
request-scoped ORM work in FastAPI. Config saves accept explicit configuration
and preserve CSRF-before-auth and outbound URL validation. Tests inject fake
adapters and prevent any device/network probe during focused verification.
The member filter bundle, library-platform list, and taxonomy reads also resolve
auth and ORM work through native request scopes. The library fallback artwork
URL is now provided directly to the shared payload builder, avoiding a synthetic
Flask request context; the response error contract is built with the shared
framework-independent API helper.
The authenticated `/api/get_company_role`, `/api/search_igdb_by_id`, and
`/api/search_igdb_by_name` lookups now run in FastAPI with numeric identifier
validation where applicable and an injectable provider adapter. Name search
retains the optional platform filter and legacy result envelope; request
contracts are covered without making an external IGDB call.
The member locale GET/POST now uses the request-local session scope, pure
Starlette/API-contract responses, and the existing signed-session/CSRF
compatibility helpers without pushing Flask app context.
The authenticated `/browse_games` endpoint also uses the native DB scope. Its
pagination now runs through the shared SQLAlchemy session rather than
Flask-SQLAlchemy's request-context-aware paginator, while retaining the page
size cap, count, deterministic ordering, Flask JSON-provider serialization,
and typed duplicate-query handling.
The admin library-health summary and per-game health detail reads also use
native session scopes and Starlette JSON/error responses while retaining the
existing query parsing, role checks, scoring, and library ACL order.
The OIDC readiness endpoint now follows the same native scope and response
path; its local-only report still performs no IdP call, and role/Bearer-scope,
redirect, and HEAD behavior remain covered.
The FastAPI setup transition now passes explicit configuration and task-owner
arguments into library/font/core seed helpers, so its setup finalizer no longer
pushes a Flask application context. Legacy setup callers keep their existing
context-backed defaults; this is a bounded decoupling step, not framework
retirement.
Native Operations reads also no longer push their own Flask app context.
Configuration, database-engine access, and theme-root lookup are injected into
the existing snapshot helpers; the native request-local session remains the
ORM boundary, while legacy callers retain their defaults.
The admin `GET`/`HEAD /api/hltb/stats` endpoint also runs through FastAPI with
request-local SQLAlchemy scope. It retains the four-field coverage payload,
signed-session and admin-token checks, login redirects, no-store policy, and
HEAD behavior. Single-game and bulk HLTB refresh actions also use FastAPI with
CSRF-before-auth and existing provider adapters.
The Arr connector configuration `GET`/`HEAD`/`PUT` uses this native path. Its
shared public projection reports only whether credentials are configured;
secret values remain private. The Arr module `GET`/`HEAD`/`PUT` status/toggle
route also runs natively and stays available while the optional module is off.
The Arr indexer catalogue `GET`/`HEAD` also uses FastAPI; it reads saved
indexers and the local preset catalogue while preserving module/admin gates and
the bare payload. Indexer create/update/delete also run natively with
CSRF-before-auth, validation, and credential-redacted responses. Bulk import
and preset enablement, provider search/download, and hardlink preview/apply also
run natively. The `/api/arr/module` read/write also runs natively and stays
available while the optional module is disabled.
Single-indexer `GET`/`HEAD /api/arr/indexers/<id>` now uses the same native
router and keeps its public, credential-redacted detail projection plus the
existing not-found envelope.
SMTP settings `GET`/`HEAD` also uses FastAPI and a shared framework-independent
public projection; the password remains represented only by a saved/not-saved
flag. FastAPI `PUT` preserves CSRF-before-auth, field validation, blank-password
retention, cache invalidation, and session refresh. Its `POST /api/admin/smtp/test`
action now also checks CSRF/auth natively and calls the existing tester; tests
use a fake tester and send no mail.
IGDB settings `GET`/`HEAD` follows the same approach: its shared projection
returns the client ID, test timestamp, and a secret-presence flag without the
secret value. The FastAPI `PUT` path also preserves CSRF-before-auth,
validation, blank-secret retention, session refresh, and cache invalidation;
the FastAPI `POST /api/admin/igdb/test` route preserves CSRF, safe result/error
payloads, and the last-tested timestamp while using the existing provider
adapter.
The custom chat emoji catalogue `GET`/`HEAD` is native as well; it preserves
the admin gate, limits metadata, no-store response, and generic storage-error
contract. Its DELETE action also uses FastAPI and validates CSRF before auth;
upload remains on its established handler.
Batch favorite, play-status, and wishlist mutations now use the native ORM
scope and shared framework-independent API envelope for empty-batch successes
and errors; cookie CSRF, Bearer handling, and partial-result semantics remain
intact.
Freshness inbox and store-search routes also use request-local ORM scope and
framework-independent errors. Store probes remain behind their injectable
adapter, and query duplicate handling still uses the first value.
Trailer filter and random-selection APIs now use the native session scope;
authentication redirects, result envelopes, HEAD and safe empty/error payloads
remain unchanged. The random selection itself performs no outbound provider
request.
Social status/friends/profile/activity reads and game related-media reads and
actions now use native request-local sessions. Profile avatar URLs are built
from the app's static path without a Flask test-request context; social-scope,
ACL, validation, and cookie-CSRF contracts remain.
Gaming/free-game feed reads and wanted-update list/actions now also use native
request-local sessions. Wanted-update file storage receives the configured
upload root explicitly, and its API responses use the shared framework-neutral
contract; feed/provider calls remain behind the data adapter.
Wishlist request list/create/cancel/resolve and the member password-change
mutation also use request-local sessions and framework-neutral API responses.
Password reset still refreshes the signed user session and remember cookie, and
wishlist audit events retain the initiating user ID.
The bounded freshness scan mutation now also uses native request/session
handling. Its local version-file check receives the Flask app explicitly so
the configured game-root allowlist remains enforced without relying on
`current_app`.
Companion capabilities, presence heartbeat, command enqueue/acknowledgement,
and client lifecycle reads/writes now use the request-local SQLAlchemy scope
and framework-independent response contract. Bearer scopes, CSRF, game ACL,
command ownership, validation, session refresh, and HEAD behavior remain.
Acquire readiness also uses native DB scope and receives app configuration
explicitly; its status calculation reads local configuration and database rows
without probing indexers, debrid services, or other providers.
The admin ROM-translation capability read also dispatches through FastAPI,
keeping the bare payload, admin-role/Bearer-scope checks, login redirects,
danger flash, security headers, and HEAD behavior.
Public member loading-icon bootstrap and admin settings GET/PUT also use native
request-local ORM scope. The member projection stays safe and bare JSON; the
admin GET stays bare JSON; PUT retains browser CSRF, admin/Bearer gates, input
errors, and the shared success envelope.
FastAPI's unmatched-route, unhandled-error, and CSRF rejection responses now
build the shared JSON envelope through a framework-independent contract and
no longer enter a Flask app context. Other native route persistence and startup still depend on
Flask.
The admin runtime-bootstrap endpoint now resolves its ORM work in a
request-local SQLAlchemy session without pushing a Flask app context; member
bootstrap's OIDC-label lookup uses the same boundary. Flask routes retain their
app-context session scope. The dedicated session scope is transitional while
remaining native routers are moved off Flask.
These are bounded transition
boundaries, not a replacement primary runtime, and Flask/Jinja remain required.
FastAPI auth/setup routers cover `/login`, `/register`, reset, confirmation and the six first-run setup URLs; the duplicate optional member pilot has been retired. Setup transitions use `/api/setup/state` and `/api/setup/step`. Member and admin SPA shells now
share a React preferences dialog backed by `/api/account/preferences`; the
`/settings_panel` endpoint redirects to that dialog.
Retaining Flask session hooks
during either pilot is transitional and does not establish zero-Jinja completion.
Legacy POST handlers and form endpoints still require compatibility review, but
page rendering no longer depends on Jinja templates.

The daily digest, social notification and invite email bodies and the `/offline`
document use explicit non-template renderers. Theme and built-distribution URLs
are resolved by `oneirodex/utils/asset_urls.py`. The application no longer has
an authored template tree or Jinja render/filter/context-processor calls. This
does not remove the Flask/Jinja runtime dependency.

The member SPA page shell now uses a Python HTML builder in
`oneirodex/utils/member_spa.py`; it preserves the React root data contract,
theme/icon assets, CSRF markup, flashes, delete modal and era atmosphere without
calling Jinja. The admin-gated design-system styleguide also builds its document
without Jinja now; React-owned admin routes also use the shared Python document
builder. Their empty wrapper templates were removed along with the unused
`base_empty.html` shell and styleguide template. The app's primary route/session
runtime is still Flask.

The React-owned downloads page at `/admin/manage-downloads` uses that admin
shell and reads through the existing admin API. Its API exposes a filename
instead of the raw ZIP path, while the classic POST delete endpoint remains for
compatibility. The newsletter, invite roster, reference sets, statistics, features, themes, Server Settings, Arr, Attract Mode, discovery sections, whitelist, scan-filter, IGDB settings, chat emoji, SMTP, AI assist, admin Libraries & scans, manual identify, library add/edit, game image editor, and Libraries & scans routes also use the
shared shell; their established form POST compatibility paths remain. These
pages no longer load their former Jinja page bodies or query page state for document rendering. The React Integrations hub keeps metadata-provider and community-link editing on guarded APIs; SMTP and IGDB settings live on their dedicated React routes. The retired Jinja integration form partials and tab controller were removed.

## Runtime

| Piece                   | Role                                                                           |
| ----------------------- | ------------------------------------------------------------------------------ |
| Flask (`oneirodex/`)    | Session cookie, shell/API routes, `/api/**` + `/admin/api/**`, scans, play, social |
| member-app              | Household SPA (`frontend/member-app`)                                          |
| admin-app               | Operator SPA (`frontend/admin-app`)                                            |
| ops-glance              | Ops pulse widgets (`frontend/ops-glance`)                                      |
| `@oneirodex/api-client` | One requester, two transports (Bearer `gt_…` / browser cookie + CSRF)          |
| `@oneirodex/ui`         | Shared chrome, envelope helpers, CSRF lookup                                   |
| Desktop companion       | Tauri client on the Bearer transport                                           |

The ASGI entrypoint handles `GET /api/auth/runtime-bootstrap` directly with a
framework-independent codec that preserves Flask's signed session cookie and
Flask-WTF CSRF token format. OIDC label lookup uses request-local ORM scope.
Auth-page, setup-page, and their supported form handlers dispatch through the
mounted FastAPI routers; the optional member-shell pilot and runtime marker have
been removed. Other account mutations use native FastAPI adapters. Flask startup
remains part of the compatibility runtime.

The ASGI entrypoint serves `GET` and `HEAD /pulse` directly using a pure
liveness payload. `/awake` prepares framework-independent runtime config and a
native SQLAlchemy engine without constructing Flask, then runs the existing DB
and initialization readiness checks in request-local ORM scope and sends its
response directly from ASGI. Normal ASGI lifespan still initializes Flask to
start compatibility workers. It also
serves `/offline` directly using the member-free HTML builder, and
`/sw.js` plus `/vr/sw.js` from shipped application files with their existing
scope and no-cache headers; mutable library overrides cannot replace these
origin-wide worker scripts. `/favicon.ico` also uses the native response path
with its existing one-hour cache policy. A native FastAPI redirect handler
also serves `/` and `/index`. It keeps setup
redirects ahead of login checks, sends anonymous users to login, and sends
authenticated users to Discover; the setup utility uses the native DB session
facade when called inside this route scope. This cutover does not remove Flask
startup or the Flask extension/database ownership layer.

`/api/theme/fonts.css` now uses the native FastAPI route for anonymous and
credential-bearing requests. It preserves first-value query override,
signed-session font preference, the shared stylesheet builder, cache/security
headers, and HEAD behavior. The shared FastAPI app still initializes after
Flask during the transition. Requests to `/api/emulator/installed-cores.js`
build the existing disk-backed WebRetro
allowlist directly in ASGI with its JavaScript content type and five-minute
private cache policy.
The shared native FastAPI API app converts unmatched HTTP errors and unexpected
handler failures into the standard API error envelope, preserves safe security
headers and does not expose exception details to clients.
`/manifest.webmanifest` reads the configured site label through a request-local
ORM scope and returns the shared install manifest payload directly from ASGI
with its one-hour cache policy. `/api/loading-icon` uses the native API router
and request-local ORM scope for the member-safe settings payload. Anonymous
`/api/setup/state` also uses request-local ORM scope and retains the shared
envelope, no-store policy, security headers, and HEAD behavior.
Credential-free `GET` and `HEAD /login` and `/reset_password_request` serve the
validated React auth shell; credential-bearing requests retain Flask-Login
dispatch, and form posts remain on Flask.
`/api/setup/state` now dispatches through FastAPI for anonymous and
credential-bearing requests. In-progress wizard settings require the same
signed administrator session as the Flask route; Bearer tokens do not expose
setup-only configuration. The endpoint keeps no-store and HEAD behavior.
`/api/attract-mode/settings` and `/api/attract-mode/user-override` now dispatch
through FastAPI for anonymous and signed-session requests. Per-user filters
and autoplay settings still overlay admin defaults, and saving an override
keeps browser CSRF, auth, audit, and session-refresh behavior. The authenticated read-only browse endpoint
`/browse_games`, trailer endpoints `/api/trailers/filters` and
`/api/trailers/random`, Acquire status `/api/acquire/status`, and admin OIDC
readiness `/api/oidc/status` are direct FastAPI handlers on one router app.
Member-safe remote-play status `/api/remote-play/status` is also served there.
Admin settings-hub badges `/api/settings/module-status` use it as well.
The admin library-health summary `/api/health/library` is also native.
The complete admin quality-profile API family `/api/quality-profiles` now uses
FastAPI for list, create, save, activate, detail, update, delete, and score
actions, including CSRF on writes and the legacy bare JSON responses.
The admin statistics read `/api/admin/statistics` also dispatches through
FastAPI, keeping the existing aggregate projection, admin session/token-scope
checks, envelope, no-store response, and HEAD behavior.
The admin Identify search `/api/admin/games_search` also dispatches through
FastAPI. It preserves the admin-only full-disk-path projection, query limit,
empty-search response, and legacy error envelope.
Member command-palette suggestions `/api/palette/suggest` also dispatch
natively, retaining the signed-session member gate, ACL-filtered played and
favorite projections, and bounded result limit.
The admin metadata-provider configuration `GET`/`HEAD`/`PUT`
`/api/admin/integrations/metadata-providers` also dispatches through FastAPI,
preserving the provider projection, partial update validation, CSRF, and admin
gates.
The member licensed-catalog report, admin cache-status read, and admin IGDB
refresh action also dispatch through FastAPI with the existing member/admin
scopes and cached data contract. Refresh retains CSRF, input validation, audit,
and sanitized upstream errors.
Storage and malware status are native admin reads, and `/api/rtc/status` is a
native member read. Challenge-solver and ambient-lighting status, config and
test actions are native admin routes; optional probes retain their legacy
behavior behind adapters. The admin AI status, config, triage, doctor-notes,
and apply-triage endpoints also dispatch natively and retain their status and
action payloads (including the unreachable-Ollama `error` field), CSRF-protected
writes, and explicit auto-apply gate. Focused tests inject adapters and make no
host, device, Ollama, or game-change calls.
The admin library-platform options endpoint is also native and returns the
existing platform enum through the shared API envelope without a database read.
The admin Arr status endpoint is native as well; its status projection and
connector readiness checks retain their legacy behavior behind the same admin
and token-scope gates.
The admin theme loading-icon catalogue `/api/admin/themes/loading-icons` also
dispatches through FastAPI and keeps the shared success envelope and admin gate.
The admin theme inventory `GET`/`HEAD /api/admin/themes` also dispatches through
FastAPI with its existing metadata projection, admin gate, envelope, and HEAD
behavior; uploads and deletes remain on their compatibility routes.
The admin metadata-search source catalogue `/api/search_metadata/sources`
dispatches through FastAPI with the same bare capability projection and admin
gate; it reads local configuration only and performs no provider search.
The admin `/api/search_metadata` provider lookup route also dispatches through
FastAPI, preserving query aliases, result limits, per-source notes, and the
admin gate. Provider calls remain behind their existing adapters.
Companion capability and lifecycle reads, heartbeat, command queue/poll, and
command acknowledgment/release APIs also dispatch through FastAPI. Lifecycle reads
and command polls retain the `read:library` gate; lifecycle synchronization and
command acknowledgment retain their Bearer-only rules; browser heartbeat and
command queue writes retain CSRF, scope and ACL checks.
Announcements (including admin-only draft visibility and CSRF-protected
creation) and the gaming/free-game member feeds also dispatch natively. Provider
calls stay behind adapters so contract tests never issue outbound requests.
Member Discover feed, row-window, zone, genre-hub, surprise, pins reads and pin saves now
dispatch directly through FastAPI. The release calendar also dispatches
through FastAPI while retaining its bounded query and empty-provider fallback.
They preserve feed tokens, first-value pagination and filter
parameters, multi-segment genre paths, error envelopes, and signed-session
redirect behavior. Pin saves retain CSRF and partial-update semantics.
Member activity feed, game search, game-detail, editions, more-from, versions,
and freshness reads also dispatch through FastAPI. The detail reads keep the
existing game ACL and payload builders; versions retain the `read:library`
Bearer scope and path-redacted projection. The on-demand freshness check is a
CSRF-protected native write whose provider/data work remains behind an adapter.
The filter bundle and library-platform catalogue also dispatch natively while
retaining the member-specific library projection and optional completion flag.
Playtime summary/per-game reads, session start/heartbeat/stop actions, and the
ACL-protected playtime share-card SVG also use FastAPI; they retain per-game
visibility, session ownership, body validation, and browser CSRF. The shared game-details image projection builds
the same static URL when called without a Flask request context.
Favorites, saved filters, social friendship mutations, Acquire search/send, and
the VR catalogue/profile APIs now use the same native request-local SQLAlchemy
scope. Their query/body validation, ACL and librarian checks, CSRF, Bearer
scopes, ownership rules, URL validation, payload envelopes, and HEAD behavior
remain in the route adapters. These are migration slices; they do not remove
Flask initialization or extension ownership.
The member account API now dispatches through FastAPI: summary, invites,
preferences, stock-avatar selection, multipart avatar upload, password change,
and personal-token list/create/revoke. Existing signed-session, remember-cookie,
and route-specific Bearer behavior is retained. Mutations validate the existing
Flask-WTF CSRF token; password changes refresh the current signed session and
remember cookie with the new password fingerprint, and avatar writes preserve
the existing file validation, commit, rollback, and old-file cleanup services.
Preferences keep the current choice lists and WTForms validation contract.
Preferences, stock-avatar selection and multipart avatar upload use the native
request-local SQLAlchemy scope. Account summary and invite routes also use
request-local sessions and framework-independent response envelopes. Avatar
URLs use an explicit static URL builder; invite mail uses a quiet SMTP sender
with the existing reachability preflight and explicit audit actor. This account
API slice does not remove the Flask compatibility runtime.
Game detail, search, editions, versions, freshness, screenshot, image, and
assist APIs also run in request-local SQLAlchemy scopes. The assist projection
receives its enablement and storage configuration explicitly; the legacy Flask
assist routes retain their current-context defaults. Freshness audit events use
the authenticated actor id directly.
The member card action routes for favorite and completion status now use
FastAPI, along with the paged favorites projection, member role/username/icon
metadata, and the five standalone filter taxonomies. Social member profile and
comparison reads retain `read:social`, visibility filtering, and their existing
response shapes. VR catalogue/detail reads preserve the feature flag, page
bounds and game ACL; VR profile writes preserve librarian/admin-token checks,
browser CSRF, body validation, and the HTTP(S)-only profile URL contract. Batch
favorite, status, wishlist, freshness and artwork-refresh actions also dispatch
natively with their legacy caps and partial-success results. Favorites, saved
filters, social friendship mutations, VR routes, Acquire actions, and batch
freshness/artwork refresh now use request-local SQLAlchemy scopes and
framework-independent API envelopes; provider, database and filesystem effects
remain behind adapters where applicable.
The member locale API (`GET`/`HEAD`/`POST /api/locale`) also dispatches through
FastAPI, preserving supported-locale values, JSON and form input, browser CSRF,
the signed-session locale update, the `gt_locale` cookie, and security headers.
Its SQLAlchemy adapter uses the request-local native scope. Flask keeps the
legacy URL rule registered for route-census comparison, while ASGI dispatches
the request to the native FastAPI handler.
Discover section, row, zone, genre-hub, surprise, and pin reads also use native
request-local database scopes. They keep the existing builders, first-value
query parsing, response shapes, session redirects, security headers, and HEAD
behavior; their configured JSON provider is called without Flask request state.
The unused Flask-Babel extension was removed after a source call-site audit
found no translation calls or consumers of Babel's selected `g.locale`; the
locale values and normalizer live in framework-independent
`oneirodex/utils/locale_core.py`.
Member game-health detail `/api/health/games/{game_uuid}` keeps its per-game
access check on the native path.
They use the shared request-auth boundary and keep their existing query,
readiness and payload services plus SQLAlchemy access inside one explicit Flask
app context during the transition. Anonymous requests retain Flask-Login
redirect, flash, and signed-cookie behavior; admin OIDC access also preserves
role and token-scope checks.
Public static assets also use the direct ASGI file handler; private paths remain
denied and member BIOS still checks the existing signed session. These paths
skip Flask request dispatch; lifespan startup initializes Flask for
configuration and extension compatibility.

The ASGI activity/event streams now check event visibility and child-role
eligibility in request-local ORM scope without pushing Flask app context. Their
signed-session ID resolver uses the framework-independent Flask-cookie codec
and active-user/password-fingerprint checks.

ASGI ZIP and ROM downloads read ownership, game ACL, and download records in
request-local ORM scope. Download identity uses the signed-session codec or
native Bearer resolver, preserving fingerprint validation, token expiry and
scope checks, child restrictions, and explicit Bearer precedence over cookies.

The zero-Jinja runtime migration is incomplete. The authored template directory,
template render calls, and direct Jinja imports have been retired. The legacy
route inventory now has zero unmatched method/path pairs, and ASGI sends final
dispatch to FastAPI; the WSGI fallback and `a2wsgi` dependency are retired.
`create_app()` still constructs Flask, native session/CSRF adapters preserve
signed-cookie compatibility, and Flask-SQLAlchemy still owns mapped models and
legacy service fallbacks. These are the remaining strict runtime gates.

JSON errors go through `api_ok` / `api_error` (`oneirodex/utils/api_response.py`). Eleven sites stay off that helper on purpose — [api-envelope-keeps.md](api-envelope-keeps.md).

## SPA fetch

Admin, member, and ops sit on `createBrowserRequester`: `credentials: 'include'`, `X-CSRFToken` on mutating verbs, `onUnauthorized` → `/login`. Wrappers keep their exported names. Member collections CRUD calls `createCollectionsApi`, wishlist calls `createWishlistApi`, and notifications use the shared requester for inbox, read-state and preference operations. Those families, social status/friend reads and mutations, the wanted-update list, freshness inbox/store-search/scan, and Acquire search/send dispatch through FastAPI under ASGI and preserve browser sessions, CSRF for browser writes, role/ownership or token-scope checks, API envelopes and security headers. Acquire keeps its librarian gate, feature flags, outbound-URL validation, and sanitized provider errors. Social and notification Bearer reads require `read:social`; their writes use `write:social`. Other resource groups still call `getJson`/`postJson` directly.

Member leftovers that are not JSON verbs:

- Activity / scan toasts — `EventSource` (`/api/activity/stream`)

The SPA preferences dialog uses `GET` and `PUT /api/account/preferences`; its
choice lists come from shared theme, icon, and font registries and the retained
WTForms validation contract.

Request bodies adopt `@validate_body` **file-by-file** — [pydantic-adoption.md](pydantic-adoption.md). Partial-success batch routes use `@validate_batch_body` so the 422 keeps `updated` / `skipped` / `errors` / `limit`. Do not wrap those with the flat helper.

## Browse filters (INSP-3)

Two faces, **one vocabulary**. The flat chip params (`is_vr`, `freshness_behind`,
`new_import`, `path_status=`, `name=` …) and the nested tree both compile through
`FIELDS` in `oneirodex/utils/filter_tree.py`, so a field has exactly one clause
builder and the two cannot drift apart.

| | |
|---|---|
| Tree shape | `{"op": "and"\|"or"\|"not", "nodes": [...]}` groups; `{"field": …, "value": …}` leaves |
| Vocabulary | **only** the fields in `FIELDS` — a tree cannot reach a column the chip row cannot, join a new table, or express a comparison nobody shipped |
| Bounds | `MAX_DEPTH` 6, `MAX_NODES` 60 |
| On browse | `GET /browse_games?filter_tree=<json>` — a **conjunct beside** the chips, never a replacement |
| Bad tree | `400` naming the offending part (`detail.path`, e.g. `root.1.0`), never silently dropped |
| Negation | `NOT` folds SQL's third value away (`coalesce(expr,false)`), so *not behind* includes rows the field was never set on |

Adding a field is a deliberate edit to `FIELDS` — it is not a side effect of the
model gaining a column.

Named filters are per-member (`SavedFilter`, Alembic `c3d4e5f6a7b8`):
`GET|POST /api/filters/saved`, `PUT|DELETE /api/filters/saved/<id>`,
`POST /api/filters/preview` (count + optional sample, through the member's own
access filters), `GET /api/filters/fields` (what a builder may offer). The
`is_collection` flag is what makes the same row a smart collection (INSP-29)
rather than a second table. No admin view, no sharing surface.

## Identifiers (ADR 0003)

Runtime env is **`ONEIRODEX_*` only**. `GT_*` is not read. `LEGACY_NAME = 'GameTheca'` stays so stock themes authored by older versions are still recognised. On-wire API tokens keep the `gt_` prefix. Danger-zone confirm is `RESET ONEIRODEX` (no legacy alias).

## Frozen / do not drive-by

- `oneirodex/updateschema.py` — historical SQL; Alembic is the migrator
- Shims: `oneirodex/utilities.py`, `oneirodex/utils/functions.py`, `oneirodex/utils/game_core.py`
- Envelope keep-list of 11
- Mega pages (GameDetails, Library, Chat, Discover) stay typed in place — no decomposition PRs

## P17 native admin API progress

The FastAPI compatibility router currently owns the HLTB coverage, single-game,
and bulk refresh actions; Arr configuration, indexer catalogue, CRUD, bulk,
preset, search, download and hardlink preview/apply actions; SMTP and IGDB settings/test actions; custom chat emoji
listing and deletion; admin theme inventory/upload/delete; and admin reference-set listing, multipart upload, and
deletion. Reference-set uploads use the pinned `python-multipart` parser, cap
file reads at 32 MiB, check CSRF before authorization, and preserve the
replacement-confirmation response. The companion `/api/reference-sets` route
preserves its signed-in member list response and admin upload/delete shapes.
The same router also serves the member set-completion report and admin
reference-set rehash and dry-run repair-preview actions, the complete Quality
Profiles API family, and Discover pin saves; tests inject fake
adapters so these workflows are not run against the local library during
verification.
The native game API router also owns the arcade input-family patch, keeping its
librarian/token-scope gate, CSRF check, game ACL and closed vocabulary outside
Flask request context. It also serves the next-custom-IGDB-ID read and the
admin bulk freshness refresh action and librarian game-to-library move through
request-local database scope. Native library catalogue, detail, and watch
reads preserve member ACL and count projections; admins can read library
details, reorder and batch-edit libraries, and librarians can update the library watch
flag, through the same request-local router. The FastAPI notifications router also owns
the admin test event publish action, alongside the notification-bus test. The
native chat emoji catalogue serves both the member and admin catalogue reads.
The member chat read router now also serves channel creation, channel and space
lists, message reads and search. Message reads retain the legacy read marker;
channel creation, mute, archive, leave and open-DM actions use native CSRF
validation and the `write:social` token scope. Message posts and reactions are
also native. Attachments, custom emoji writes and remaining space APIs still
use the compatibility router. Chat attachment downloads now use a native
FastAPI file response after member/channel authorization and safe directory
resolution; upload remains on the compatibility route. The chat-space list,
create/channel actions, member and invite management, join flow and voice-room
lookup now use the native router. Chat attachment upload and custom emoji writes
also use native FastAPI multipart handlers. Storage helpers accept explicit
upload settings so these routes do not need Flask's application context; the
multipart bodies are capped before parsing and the file parts are closed.
The eight detail-layout APIs (install default, member override and named
presets) also dispatch through FastAPI with request-local database scope.
These routes still initialize Flask in the outer ASGI lifespan and do not imply
that P17's strict runtime gate is complete.


P17 adds FastAPI reads for store-ownership provider policy, stored connections, summary, review titles/candidates, match/undo and sync cancellation, plus emulator catalogue/per-platform options. The ownership review reuses owner-scoped, ACL-filtered and revision-checked service functions; provider sync calls are not performed by these read APIs. The emulator routes retain member authentication and generic unsupported-platform errors. These additions still use Flask configuration/auth/database compatibility objects during outer ASGI startup and do not close the no-Flask runtime gate.

The emulator settings slice adds admin-only profile reads and saves through the same native router; browser writes retain CSRF checks and the existing profile validation/storage service.

The native emulator settings router also serves the admin preferred-core catalogue and browser-player defaults, including CSRF-protected configuration writes; it reuses the existing validation and settings services.


The native library freshness action also passes explicit app configuration into the shared freshness service, avoiding a Flask context for its root checks.
The native Steam metadata backfill now uses the existing request-local session directly, without wrapping provider hydration in Flask context. The background library-wide force-refresh worker remains Flask-bound.

Its route regression tests exercise the real native request-local SQLAlchemy scope on in-memory SQLite, with Flask app-context entry forbidden.

The unmatched-folder mutation router now runs its request/auth/CSRF handler inside
only the native request-local database scope, without pushing a Flask app context.
Its adapters also avoid nested contexts for kinded-game creation and explicit-actor
audit, retry matching, and guarded update placement. It still receives Flask config,
URL-map, and login-manager compatibility objects; the outer Flask lifecycle and
strict runtime gate remain.

The native system API router also handles allowed-root path availability checks
and admin allowed/ignored file-type CRUD. It preserves the legacy response
payloads, admin/token scope rules, CSRF order, extension validation and safe
existence checks. These route families still share the existing auth/config
compatibility bootstrap; they do not remove Flask startup or extension ownership.

Admin library-root inventory and folder browsing now use the native router,
with the existing signed-session/admin gate, configured-root resolver,
allowlisted-path checks, and GET/HEAD response behavior. Ownership connection
and import actions (connect, disconnect, sync, sync-all, and CSV) also dispatch
through FastAPI with CSRF-before-auth and the existing store validation and
payload compatibility. Both slices use adapter boundaries for focused tests;
they still depend on the shared Flask configuration and session compatibility
objects during startup.

Emulator cheat/save and BIOS APIs, the game-server registry, and game-mod,
catalogue, and profile APIs are also mounted in the native router. Emulator
multipart uploads are bounded before parsing. These endpoints retain the
existing auth and ACL rules and keep writes and probes behind data adapters,
but the overall application still builds Flask for configuration and extension
compatibility. Registered HTTP routes dispatch through native ASGI/FastAPI.

Unmatched-folder listing, duplicate comparison, fix-log reads, and CSV/JSON
exports also use FastAPI. Their query aliases, post-region pagination,
projection fields, admin redirects, and download headers remain compatible;
mutation and maintenance endpoints are separate and remain on their current
routes.


Unmatched-folder mutation routes now dispatch through FastAPI as well: soft-name edits, bounded batch triage, duplicate-fix logging, mark-kind, retry matching, and guarded update placement. Authorization, CSRF order, and source/destination library-path checks are retained, with external and destructive effects behind test adapters. This is API parity work; it does not retire Flask startup or extension ownership.

Library inspection and preview APIs now include native FastAPI handlers for manual-identify preview, leaf-library proposals/import preview, proposal listing and scanning, and library-doctor dry-run. Path checks and parsing are adapter-backed in focused tests; remaining library-tools mutation and scan-queue routes still use compatibility dispatch. Unmatched maintenance now also covers duplicate reclassification/backfill and bad-match feedback. These endpoint migrations retain Flask configuration/session compatibility during startup.

The native library-tools write slice now covers rename preview, proposal approval, and doctor proposal writes; each route uses the existing admin/session/token checks, CSRF validation, and adapter-backed side effects. Remaining scan-queue and filesystem mutation routes still use compatibility dispatch.

Admin library creation, batch scans, and batch deletion now use FastAPI routes with explicit admin/token authorization, CSRF checks, caps and typed deletion confirmation. Durable database, image, scan and deletion-job work remains behind adapters while route parity is established.

Manual-identify preview/queue, support-ticket list/detail reads, and the theme-font catalogue now have native FastAPI dispatch. The scan queue preserves the idle preview and explicit busy-scan choices; support reads remain browser-session-only and owner-scoped for members. The font inventory keeps its existing `fonts_dir` response field pending later exposure review.

A source-level API route comparison is maintained as an estimate only: it cannot establish that each FastAPI router is mounted behind the correct ASGI method gate or that behavior matches. Runtime dispatch checks remain necessary for each migrated family.

Read-only provider and patch-catalog registries plus the admin integrations inventory now use native FastAPI dispatch, preserving their legacy response shapes and authorization. Provider calls were not part of these catalog reads. The server-local path fields remain for parity and need review in the planned security scrub.

Artwork-provider searches and the admin artwork-apply action now dispatch through native FastAPI routes. Artwork writes retain signed-session CSRF and admin/token-scope checks, bounded input validation, provider and image-kind restrictions, and the existing artwork service behind an adapter. Launcher import writes are also native and remain upload-bounded and feature-gated. Flask startup and ORM ownership remain active while semantic parity and dependency retirement continue.

The admin attract-mode settings API now uses native FastAPI dispatch for reads and saves. Typed schema validation, CSRF-before-auth, admin token scope, filter-option projection, and audit/cache updates remain in place; the surrounding app still uses Flask for startup and uncaptured routes.

Admin feature preferences and challenge-solver configuration now also dispatch natively. The migration preserves the fixed seven-field preference contract, read-only process flags, challenge validation and safe probe projection, with the operator action still routed through its existing adapter.

The admin scan-filter catalogue also uses native FastAPI reads and writes. It keeps the legacy pattern taxonomy and case-sensitivity rules, validates regular expressions before persistence, and gates mutations with signed-session CSRF and admin authorization.

The local plugin catalogue and detail endpoints now use native FastAPI reads with admin and token-scope checks. Plugin discovery stays read-only and uses the existing catalogue service.

Single-library admin edits now use native FastAPI dispatch for JSON and multipart submissions. The editor retains CSRF and admin authorization, bounded image conversion, metadata validation, and the existing audit behavior.


The admin single-library scan endpoint now dispatches through FastAPI with the same signed-session admin gate, CSRF ordering, configured scan-root validation, queue policy, schedule fields, and scan flags. The scan service remains behind an adapter for focused tests. This route migration does not retire the Flask-backed ASGI lifespan or SQLAlchemy ownership layer.


`POST /api/admin/libraries/refresh_all` also dispatches through FastAPI. It preserves FIFO job creation, the legacy busy check before enqueue and promotion when idle, plus the explicit force-parallel worker. These routes still use compatibility configuration/session/database objects until the primary runtime migration is complete.


The admin scan-job status poll now dispatches natively for GET and HEAD. It retains server-side filters, timing projections, queue-position lookup, and the best-effort idle drain. The route uses the existing admin/session compatibility callbacks while the main Flask lifecycle remains.

The manual-identify editor create and update APIs now dispatch through FastAPI.
They retain admin and token-scope checks, browser CSRF, path/library validation,
duplicate detection, metadata writes, unmatched cleanup, audit events, and image
refresh scheduling. Folder-size and NFO helpers accept explicit allowed roots so
the native adapter does not need Flask request-local state. The native runtime
context now supplies a SQLAlchemy-only context manager for background work;
scheduled scan and queue-drain workers receive an explicit native session
scope. Flask services and package dependencies remain to be retired.

Library inspection and manual-identify preview adapters now use the request's
native SQLAlchemy session and their explicit app configuration directly; path
resolution, scan-mode selection, and candidate enumeration no longer push Flask
app contexts. Folder enumeration also avoids writing a flash message when it is
called outside a Flask request.

Unmatched-folder row projections now live under `oneirodex.utils`, shared by
legacy and native routes. FastAPI adapters no longer dynamically load a Python
module from the legacy API route tree; compatibility exports remain for older
imports while their callers transition. The native unmatched read routes pass
app configuration into cover URL projection and no longer push Flask app
contexts for list, export, or duplicate comparison responses. Feedback routes
also run auth/CSRF dispatch without Flask app context; explicit-actor audit
writes and native library/game lookups use the scoped SQLAlchemy session.
Library-tools link, rename, and doctor-apply actions also use the scoped session
without app-context pushes; link audit events carry the authenticated actor ID.


The scan module's status poll and desktop path-info endpoint now use FastAPI dispatch. The latter only reports the supplied path and its existence metadata to an authorized admin; filesystem opening remains a desktop companion action.


The admin Newsletter SPA now uses native FastAPI routes for history/readiness, detail, and send. Reads remain no-store and redact historical transport errors; sends retain CSRF/admin gates, recipient validation/deduplication, and the existing delivery service behind an adapter.


The IGDB availability lookup now uses a native FastAPI read route and the existing game lookup helper. It keeps member authentication and the legacy availability response without calling the IGDB provider.


Member email-confirmation API requests now use FastAPI with the existing timed token format and confirmation state transitions. The React auth shell keeps its current JSON contract; login, registration, password-reset APIs, and the Flask startup gate remain separate work.


The admin Server Settings React API now has FastAPI GET/HEAD/PUT dispatch with safe projection, scoped admin access, CSRF-protected partial updates, and no-store reads. Flask startup remains during strict framework retirement.


The React auth shell password-reset confirmation endpoint now uses FastAPI with the existing signed-session compatibility, CSRF, token-expiry, and password-validation contract. Reset-email delivery remains on the compatibility route while its rate-limit and mail side effects are migrated separately.


The React auth shell password-reset request and confirmation endpoints now use FastAPI with CSRF/session compatibility, per-IP throttling, non-enumerating responses, and token/password rules. Mail and persistence remain behind an injectable boundary during route parity work.


The React auth shell password-reset request and confirmation endpoints now use FastAPI with existing session/CSRF compatibility, per-IP throttling, trusted proxy handling, non-enumerating responses, and token/password rules. Email delivery and persistence remain isolated behind the native adapter during migration.


The member auth APIs for login and registration now use FastAPI. They retain the existing session/remember-cookie format, credential throttling and account-state rules, invite/whitelist transaction, and confirmation mail contract while the remaining compatibility runtime is migrated.


The static member auth shell login/register/password-reset APIs and the `/logout` redirect now dispatch through FastAPI, preserving signed sessions, CSRF, remember cookies, account policy, and invite/reset flows.


The member authentication page URLs serve the built React shell through FastAPI for GET/HEAD, preserving signed-session redirects, token checks, flash notices, and no-store behavior. Classic login, invite registration, reset-request, reset-confirmation, invite creation, and invite deletion form POSTs now use native FastAPI adapters with form CSRF and existing session-cookie behavior. `/user/invites` GET/HEAD retains its signed-session and admin warning behavior; invite mutations use the existing account-invite data adapter and preserve the library redirect/API response contracts. Native account invite APIs also carry a validated request origin into invite URL construction, preferring configured Site URL and retaining the trusted-host allowlist/private-network rules without a Flask request context. The opt-in `/demo` sign-in also uses a native user lookup and writes the same fresh signed session before redirecting to Discover.


First-run setup page GET/HEAD routes serve the built React shell through FastAPI with step redirects, signed admin access, flashes, and setup-step initialization preserved. The JSON transition API and classic form POST routes now share native FastAPI dispatch and transition logic.


The runtime config builder is framework-independent and shared by the compatibility factory. FastAPI creates its native SQLAlchemy engine directly from that config and disposes it during ASGI shutdown, rather than reading Flask-SQLAlchemy's private engine registry. Native request and worker scopes expose that config through a context-local accessor and bind the native SQLAlchemy session; service helpers use a small compatibility fallback only when called from the legacy Flask app. Normal ASGI startup no longer constructs Flask; Flask-SQLAlchemy remains installed for compatibility services and legacy callers. This boundary change does not complete strict zero-Jinja runtime removal.


FastAPI's force-refresh coordinator and per-game scan workers receive the same explicit native DB scope. Scan, identify, enrichment, image, and scan-only filesystem/filter/quality/catalog helpers resolve persistence through the native session facade when that scope is active; legacy callers continue to fall back to Flask-SQLAlchemy. Importing the scan, identify, enrichment, and image modules together no longer loads Flask/Jinja. Malware policy receives explicit runtime config, and local metadata reads/writes accept explicit allowed directory bases. Native enrichment and scoped image download helpers avoid their own Flask context pushes. Native force-refresh and per-game orchestration also skip their Flask app-context pushes when the native scope is supplied; legacy worker entry points keep their context behavior. Some downstream image helpers and other image entry points still require Flask context. The targeted scan probes below validate only empty-root, cached-game, and provider-off unmatched folder cases; they do not validate the full scan path or all image helpers. These remain runtime migration gates.


The scan orchestration module itself now imports without Flask/Jinja: legacy form dependencies load only when their Flask handlers run, and the worker accepts an explicit app plus database-scope factory. Native worker session cleanup supports direct SQLAlchemy sessions. Native forced refresh supplies its app and database scope explicitly and no longer pushes an outer or per-game Flask app context. Legacy scan callers retain their original context setup. Authenticated scans on isolated v1.1.8/current builds queue and complete for an empty read-only `/storage`, a cached-existing-game folder, and a new folder that remains unmatched when providers are disabled. The no-match branch uses Flask-optional flash/context helpers. Native scan-status safety-drain promotion now carries its database scope into the promoted worker. Successful live-provider identification, local metadata, file-mode scans, writable/destructive effects, recurring schedules, and end-to-end queue promotion/drain parity remain open.


The FastAPI worker scope also reaches game admission, identify, deferred post-identify enrichment, and image persistence/download coordinators. Their DB sessions use the direct native engine. The worker context reduction is limited to native force-refresh and its per-game orchestration; image refresh and other legacy/background entry points still use Flask app contexts.

The root install manifest (`/manifest.webmanifest`) now reads site branding through the native request-local database scope and uses runtime security headers. GET/HEAD requests are handled before Flask initialization; this removes another first-request dependency on the Flask app context while preserving the public cache policy and manifest payload.

The legacy `/restricted` page now uses FastAPI redirect handling. Anonymous requests retain the login message and `next=/restricted` target; authenticated requests continue to `/welcome`, with cookie and security-header behavior kept in the native handler.

The `/downloads` URL now resolves to the authenticated member shell directly, where the existing React Downloads page already owns the view. The legacy `/playromtest` URL also uses the member shell and retains its informational flash message.

`/play_game/<uuid>` now uses FastAPI for the existing browser-play decision. The native route retains the library ACL check, browser-play URL, missing/inaccessible-game redirects, and user-facing flash messages.

`/game_details/<game_uuid>` now uses the native authenticated member shell. It validates the UUID, checks game existence and the user’s library/content ACL before serving the React shell, preserving the legacy 404 and 403 outcomes.

The GET/HEAD compatibility redirects for `/settings_profile_view`, `/settings_password`, and `/settings_panel` now run in FastAPI and retain their existing account/preferences destinations. Their mutation methods remain on the compatibility path while those flows are migrated.

The main `/library` page now builds its React shell in the native member router. It retains default preference creation, URL-over-cookie filter precedence, library-name resolution and flash redirect, user sort/page preferences, and the catalog/scan/unmatched counts used by empty states.

The native `/library` shell also preserves first-visit behavior: if the authenticated user has no preferences row, the request creates it through the native session before building the shell.

The authenticated `/dev/styleguide` page now runs through FastAPI. Its renderer accepts explicit user, session, CSRF, asset-root, and static-path inputs, so the native path keeps the theme/icon specimen and flashed messages without Flask request globals.

The member download polling endpoint `/check_download_status/<id>` now uses FastAPI and the native session. It keeps per-user ownership, invalid/missing status envelopes, cache policy, and security audit logging.

The legacy GET form of `/delete_filter/<id>` redirects through FastAPI to the admin Scan Filters page with its warning flash. Its CSRF-protected POST deletion now also runs through FastAPI, commits through the native session, flashes success, and returns to the same page.

The legacy POST `/delete_download/<id>` form now uses FastAPI with a bounded form parser, CSRF validation, and a row lookup scoped to the signed-in user. It keeps the `/downloads` redirect and removal flash.

The admin POST `/delete_download_request/<id>` form now uses FastAPI with CSRF and admin/token-scope checks, preserves the success/not-found flashes and `/admin/manage-downloads` redirect, and deletes through the native session.

The artwork refresh progress poll (`/check_image_refresh_progress/<game_uuid>`) now uses the native admin session and role checks. Cached progress records are returned verbatim (including a job's `error` state); a missing record retains the existing `not_found` envelope. Focused native admin progress and route-matcher tests passed 7/7.

The library deletion progress paths now use native admin auth: `/check_deletion_progress/<job_id>` returns the existing raw worker state or the legacy not-found envelope, and `/delete_library_progress/<job_id>` streams the same SSE status events, headers, polling cadence, and terminal cleanup. The active completed-job test verifies the stream framing and state cleanup without starting a deletion worker.

Legacy admin scan-job cancel, delete, and clear form actions now dispatch through FastAPI. The native routes use bounded form parsing, Flask-compatible form/header CSRF, existing admin/session/token-scope checks, native DB sessions, session flashes, and redirects to `/admin/scan_management?active_tab=jobs`. Restart now uses the shared scan-queue transition and passes the explicit native DB scope into its worker, so the worker and subsequent queue drains do not require Flask app contexts.

The scan queue module now imports without Flask/Jinja and resolves Flask's `current_app` lazily only for legacy callers. Native restart work imports the framework-free scan orchestrator directly, and the DB scope follows the restarted worker and queue promotion path; the fake-backed worker test forbids Flask app-context use. No real scan was run.
