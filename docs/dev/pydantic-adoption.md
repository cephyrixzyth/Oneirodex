# Pydantic request-validation adoption (wave A2.4)

`oneirodex/utils/validation.py` adds `@validate_body(Model)`. It reads
`request.get_json(silent=True)`, validates it against a `pydantic.BaseModel`
from `oneirodex/schemas/`, and on failure returns **one** shape:

```
api_error('Invalid request.', code='unprocessable', detail={field: message})   # HTTP 422
```

On success the parsed, typed model is passed to the view as the **`body`
keyword argument**.

Partial-success batch routes (`ok` means "did every item succeed") use
`@validate_batch_body` instead. The 422 is the same `unprocessable` +
`detail={field: message}` shape, plus `updated=[]` / `skipped=[]` /
`errors=[]` and optional `limit`, so `batchActions.ts` does not see a blank
envelope. Do **not** wrap those routes with the flat helper.

## Writing a route with `@validate_body`

1. Add the model to `oneirodex/schemas/<surface>.py` (one module per route
   file). `model_config = ConfigDict(extra='forbid')` unless the route
   genuinely accepts pass-through keys.
2. Decorate the view. `@validate_body` goes **innermost** — directly above
   `def`, below every auth decorator:

   ```python
   @apis_bp.route('/collections', methods=['POST'])
   @login_required
   @validate_body(CreateCollectionBody)
   def create_collection(body: CreateCollectionBody):
       name = body.name[:120]
       ...
   ```

   Decorators apply bottom-up, so auth runs first and validation second. A
   `@validate_body` route with no auth decorator above it is a bug.
3. Delete the now-redundant `data = request.get_json(...)` line and the
   `if not data.get('x'): return api_error(...)` guards the model now covers.
4. Keep *semantic* checks that need the DB or app state (does this row exist,
   is the caller an admin, is every uuid in the collection) in the view — the
   model only covers shape, type and presence.
5. The happy-path response must not change. You are only changing the
   *rejection* shape (ad-hoc `code='bad_request'` → uniform `code='unprocessable'`,
   400 → 422) and only for genuinely malformed input.

Partial-success batch routes use `@validate_batch_body(Model, limit=N)` the
same way (innermost, under auth). Pass `extra_on_error=` when the refusal
also carries `cap` / `requested` / per-id `results`.

### `detail` shape

`{field: message}` (or `{field: [messages]}` when a field has more than one
error). `field` is dotted: `'name'`, `'items[1].id'`, `'__root__'` for a
whole-body error. `message` is pydantic's own short text ("Field required",
"Extra inputs are not permitted", ...). The offending value, pydantic's help
URL and any `ctx` object are **dropped** — `detail` never carries request data
or environment detail.

### Malformed / absent body

`request.get_json(silent=True)` returns `None` for a missing body, a
non-JSON content type, or broken JSON. All three validate `{}` against the
model: a model with required fields → 422 naming them; an all-optional model
→ accepted. A body that is valid JSON but not an object (`[]`, `"x"`, `5`)
→ 422, not 500.

## Adopted so far

52 routes (PRs #80–#96 plus named-field leftovers) on `@validate_body`, plus
`games_batch_favorite` on `@validate_batch_body`. Prefixes below match the
Flask blueprints (`/api` for `routes_apis/`).

| File | Route | Model |
|---|---|---|
| `routes_apis/collections.py` | `POST /api/collections` (`create_collection`) | `CreateCollectionBody` |
| `routes_apis/collections.py` | `POST /api/collections/<uuid>/items` (`add_collection_item`) | `AddCollectionItemBody` |
| `routes_apis/collections.py` | `PUT /api/collections/<uuid>/items/order` (`reorder_collection_items`) | `ReorderCollectionItemsBody` |
| `routes_apis/collections.py` | `POST /api/announcements` (`create_announcement`) | `CreateAnnouncementBody` |
| `routes_apis/ownership.py` | `POST /api/ownership/steam` (`connect_steam`) | `ConnectSteamBody` |
| `routes_apis/support.py` | `POST /api/support/tickets` (`support_ticket_create`) | `CreateSupportTicketBody` |
| `routes_apis/playtime.py` | `POST /api/playtime/sessions` (`playtime_start`) | `StartPlaytimeSessionBody` |
| `routes_apis/wishlist.py` | `POST /api/requests` (`create_request`) | `CreateWishlistRequestBody` |
| `routes_apis/wishlist.py` | `PATCH /api/requests/<id>` (`resolve_request`) | `ResolveWishlistRequestBody` |
| `routes_apis/tokens.py` | `POST /api/tokens` (`create_api_token`) | `CreateApiTokenBody` |
| `routes_apis/related_media.py` | `POST /api/games/<uuid>/related_media` (`related_media_create`) | `CreateRelatedMediaBody` |
| `routes_apis/library_tools.py` | `POST /api/library_tools/proposals/approve` (`approve_proposal`) | `ApproveProposalBody` |
| `routes_apis/library_tools.py` | `POST /api/library_tools/proposals/scan_roots` (`scan_roots_for_proposals`) | `ScanRootsBody` |
| `routes_apis/library_tools.py` | `POST /api/library_tools/doctor/dry_run` (`library_doctor_dry_run`) | `DoctorDryRunBody` |
| `routes_apis/library_tools.py` | `POST /api/library_tools/doctor/write_proposals` (`library_doctor_write_proposals`) | `WriteProposalsBody` |
| `routes_apis/library_tools.py` | `POST /api/library_tools/doctor/apply_renames` (`library_doctor_apply_renames`) | `ApplyRenamesBody` |
| `routes_apis/library_tools.py` | `POST /api/library_tools/check_freshness` (`library_tools_check_freshness`) | `CheckFreshnessBody` |
| `routes_apis/chat.py` | `POST /api/chat/channels/<id>/mute` (`chat_channel_mute`) | `MuteChannelBody` |
| `routes_apis/chat_spaces_api.py` | `POST /api/chat/spaces/<id>/members` (`chat_space_member_add`) | `AddSpaceMemberBody` |
| `routes_apis/quality_stats.py` | `PUT /api/quality-profiles/active` (`quality_profiles_set_active`) | `SetActiveQualityProfileBody` |
| `routes_apis/quality_stats.py` | `POST /api/quality-profiles/score` (`quality_profiles_score`) | `ScoreReleaseBody` |
| `routes_apis/emulator_cheats.py` | `POST /api/games/<uuid>/pc_cheats` (`pc_cheats_create`) | `CreatePcCheatBody` |
| `routes_apis/client.py` | `POST /api/client/lifecycle` (`client_lifecycle_post`) | `ClientLifecycleBody` |
| `routes_apis/wanted.py` | `POST /api/updates/wanted` (`updates_wanted_add`) | `AddWantedBody` |
| `routes_apis/wanted.py` | `POST /api/updates/wanted/fulfill` (`updates_wanted_fulfill`) | `FulfillWantedBody` |
| `routes_apis/vr.py` | `PATCH /api/games/<uuid>/vr_compat` (`game_vr_compat_patch`) | `VrCompatBody` |
| `routes_apis/storage.py` | `POST /api/storage/hardlink/preview` (`hardlink_preview`) | `HardlinkBody` |
| `routes_apis/storage.py` | `POST /api/storage/hardlink/apply` (`hardlink_apply`) | `HardlinkBody` |
| `routes_apis/game_servers.py` | `POST /api/game-servers` (`create_game_server`) | `CreateGameServerBody` |
| `routes_apis/malware_scan.py` | `POST /api/admin/malware-scan` (`malware_scan_run`) | `MalwareScanBody` |
| `routes_apis/acquire.py` | `POST /api/acquire/download` (`acquire_download`) | `AcquireDownloadBody` |
| `routes_apis/user.py` | `POST /api/check_username` (`check_username`) | `CheckUsernameBody` |
| `routes_apis/layouts.py` | `POST /api/layouts/detail/presets` (`layouts_detail_presets_post`) | `CreateLayoutPresetBody` |
| `routes_apis/patch_catalog.py` | `POST /api/patch-catalog/attach` (`patch_catalog_attach`) | `AttachPatchGuideBody` |
| `routes_apis/providers.py` | `POST /api/games/<uuid>/artwork/steamgriddb` (`steamgriddb_apply_artwork`) | `ApplyArtworkBody` |
| `routes_apis/account.py` | `POST /api/account/avatar/stock` (`account_stock_avatar`) | `StockAvatarBody` |
| `routes_apis/account.py` | `POST /api/account/password` (`account_password`) | `ChangePasswordBody` |
| `routes_apis/ai_assist.py` | `POST /api/ai/apply-triage` (`ai_apply_triage`) | `ApplyTriageBody` |
| `routes_admin_ext/system.py` | `POST /admin/api/discovery_sections` (`create_discovery_section`) | `DiscoveryShelfBody` |
| `routes_admin_ext/system.py` | `PUT /admin/api/discovery_sections/<id>` (`update_discovery_section`) | `DiscoveryShelfBody` |
| `routes_admin_ext/system.py` | `POST /admin/api/discovery_sections/order` (`update_section_order`) | `UpdateSectionOrderBody` |
| `routes_admin_ext/system.py` | `POST /admin/api/discovery_sections/visibility` (`update_section_visibility`) | `UpdateSectionVisibilityBody` |
| `routes_admin_ext/game_delete.py` | `POST /delete_full_game` (`delete_full_game`) | `DeleteFullGameBody` |
| `routes_admin_ext/game_images.py` | `POST /delete_image` (`delete_game_image`) | `DeleteGameImageBody` |
| `routes_admin_ext/libraries.py` | `POST /api/library/preview-cropped-image` (`preview_cropped_image`) | `PreviewCroppedImageBody` |
| `routes_admin_ext/images.py` | `POST /admin/api/covers/search` (`covers_search_single`) | `CoverSearchBody` |
| `routes_admin_ext/images.py` | `POST /admin/api/covers/apply` (`covers_apply_single`) | `ApplyCoverBody` |
| `routes_admin_ext/images.py` | `POST /admin/api/artwork/generate` (`artwork_generate`) | `GenerateArtworkBody` |
| `routes_admin_ext/art_studio.py` | `POST /admin/api/art-studio/preview` (`art_studio_preview`) | `ArtStudioPreviewBody` |
| `routes_admin_ext/art_studio.py` | `POST /admin/api/art-studio/generate` (`art_studio_generate`) | `ArtStudioGenerateBody` |
| `routes_admin_ext/art_studio.py` | `POST /admin/api/art-studio/apply` (`art_studio_apply`) | `ArtStudioApplyBody` |
| `routes_arr.py` | `POST /api/arr/download` (`arr_download`) | `ArrDownloadBody` |
| `routes_arr.py` | `POST /api/arr/hardlink/preview` (`arr_hardlink_preview`) | `ArrHardlinkPreviewBody` |
| `routes_apis/game.py` | `POST /api/games/batch/favorite` (`games_batch_favorite`) | `BatchFavoriteBody` (`@validate_batch_body`) |

### Contract notes for the adopted routes

- **`create_collection`** — missing/blank `name` was `400 "A name is required"`,
  now `422 {detail:{name:"..."}}`. Frontend (`member-app/src/api/collections.ts`)
  renders `data.error`; no code branches on the 400 or the message.
- **`add_collection_item`** — an absent/empty `game_uuid` previously fell
  through to `404 "Game not found"`; now `422 {detail:{game_uuid:"..."}}`.
- **`reorder_collection_items` / `add_collection_item`** — `@validate_body`
  runs before the per-object `_editable_collection` check, so a logged-in
  caller who cannot edit the collection **and** sends a malformed body now
  gets 422 instead of 403. Auth (`@login_required`) is unchanged; only the
  order of the object-ownership refusal vs. body validation moved.
- **`connect_steam`** — same ordering note: the `is_ownership_sync_enabled()`
  feature-flag refusal (403) now runs *after* body validation, so
  `POST /api/ownership/steam` with a malformed body returns 422 even when sync
  is switched off. A well-formed body still hits the 403. Happy path (valid
  `steam_id`, feature on → 201) is byte-identical.
- **`support_ticket_create`** — missing/blank `title` was `400 "A title is
  required"`, now `422 {detail:{title:"..."}}`. Unknown `area` / `kind` /
  `severity` still coerce in the view. Member Report form always sends a
  title; it renders `err.message` and does not branch on the old 400.
- **Wave #81–#96** — missing/blank required fields that used to be
  `400 bad_request` with an English sentence are now `422 unprocessable`
  naming the field (or `__root__` for `url or magnet` / `pack_id or id`
  after-validators). Feature-flag, librarian, child-ACL, and "scan running"
  refusals stay in the view and still 403/404 **after** a well-formed body.
  Frontends render `err.message` / `data.error`; they must not branch on the
  old 400 string. Passwords are not stripped. Usernames that historically
  used `if not username` without strip are not stripped.
- **`update_section_order` / `update_section_visibility`** — missing
  `sections` / `section_id` / `is_visible` was 400 via
  `validate_json_request`. Now 422. Negative order still 400; unknown ids
  still 404. A missing Content-Type is 422 instead of 500 (bare `get_json()`).
  Theme JS posts dataset string ids; pydantic coerces them.
- **`covers_search_single`** — missing query and uuid was 400, now 422
  naming `__root__`. Unknown uuid still 404 after a well-formed body.
- **`quality_profiles_set_active`** — missing `id` / `active_id` /
  `profile_id` was 400, now 422 naming `__root__`. Unknown ids still 404.
- **`games_batch_favorite`** — missing `favorite` / `uuids` was 400 with
  `updated`/`skipped`/`errors`/`limit`. Now 422 `unprocessable` with the
  same extra keys plus `detail` naming the field. Over-limit is still 400.
  Happy-path `ok` is still "did every item succeed" (not `api_ok`).

## Deliberately not adopted (and why)

Leave these until the contract can be preserved; do not force them.

### `routes_apis/game.py` (batch routes in `game_batch.py` since H-D.4)

- `games_batch_favorite` — **adopted** via `@validate_batch_body(BatchFavoriteBody, limit=100)`. Missing `favorite` / `uuids` is 422 with the partial-success keys; over-limit is still 400 from `_normalize_batch_uuids`; success `ok` is still "did every item succeed".
- `games_batch_status`, `games_batch_wishlist`,
  `games_batch_freshness_check`, `games_batch_refresh_images` — same
  partial-success family; take the companion next, one wrap per PR. The
  flat `@validate_body` 422 would still regress `batchActions.ts`.
- `move_game_to_library` — `tests/test_routes_apis_game.py` asserts `400` +
  `'target_library_uuid' in message` for a missing field and `400` for
  malformed JSON. Needs a bespoke validator to keep that; not a generic
  `@validate_body`.
- `admin_freshness_refresh` — every field optional with a default; admin authZ
  is done in the body, not a decorator. Nothing to delete and validation must
  not run before the admin check.

### `routes_apis/scan.py` (+ `scan_unmatched.py`, `scan_unmatched_edit.py` since H-D.4)

- The `unmatched_folders/batch/*` family (`batch_clear`, `batch_mark_kind`,
  `batch_fix`, `batch_amend`) — partial-success via `_parse_batch_ids`, whose
  rejection carries `cap` / `requested` / per-id `results`.
- `start_library_scan`, `refresh_all_libraries` — also read `request.form` and
  `request.args`; a JSON-only model cannot see the whole input. Rejections
  attach `body_status='rejected'` + `job_id` / `position` for the operator UI.
- `amend_unmatched_folder_name`, `mark_unmatched_folder_kind`,
  `fix_duplicate_unmatched`, `unmatched_flag_bad_match`,
  `backfill_unmatched_suggested_kind_route` — either attach UI-specific extras
  (`disk_rename=False`, `item_kinds=[...]`) to the refusal, or have no
  missing-field rejection to remove (so wrapping buys only `extra='forbid'`
  risk).

### `routes_apis/ownership.py`

- `connect_gog`, `connect_epic`, `connect_amazon` — **migrated (LIB-04,
  2026-09-28)** to `GogConnectBody` / `EpicConnectBody` / `AmazonConnectBody`.
  Each alias the route always read is a declared optional field rather than an
  `AliasChoices`; what the model buys is `extra='forbid'` plus length limits,
  because an unbounded note used to overflow `external_account_id` and the
  logged `DataError` carried the credential in its parameters.
- `_match_decision` (review / undo) stays on `get_json`: its documented contract
  returns 400, not the decorator's 422, for a malformed decision.
- `import_*_csv` routes — read form-data / file upload as well as JSON
  (`_read_csv_payload`). Not a JSON body.

### `routes_apis/library_tools.py`

- `propose_leaf_libraries_api` — also reads `request.args` (`root` / `path`).
- `import_leaf_libraries_preview_api` — JSON, multipart file, or form CSV.
- `rename_preview` / `rename_apply` — missing `game_uuid` is 404, not a
  presence guard.
- `library_tools_backfill_steam_metadata` — every field optional; the *success*
  body carries `updated` / `skipped` / `errors`.

### `routes_apis/chat.py`

- `chat_channels_create` — empty name/slug become `ValueError` in the helper.
- `chat_open_dm` — missing `user_id` / `username` is opaque `404 User not found`.
- `chat_messages_post` — empty `body` is allowed; `parent_message_id` /
  reactions are optional.
- `chat_message_reaction_toggle` — empty emoji is `ValueError` in the helper.

### `routes_apis/chat_spaces_api.py`

- `chat_spaces_create` / `chat_space_channel_create` — empty name is a helper
  `ValueError`.
- `chat_space_invite_create` — optional ISO / hours parsing, no required field.
- `chat_space_join` — empty token is whatever `redeem_space_invite` returns.

### `routes_apis/quality_stats.py`

- `quality_profiles_create` / `put` / `update_one` — pass-through JSON bags.

### `routes_apis/emulator_cheats.py`

- `.cht` create — JSON *or* file upload.
- Firmware plan/install — `source` falls back to `BIOS_IMPORT_SOURCE`;
  `selections` / `skipped` are optional type checks on a default empty map/list.

### `routes_apis/client.py`

- `client_heartbeat` — missing `device_id` mints a UUID.
- `client_commands_post` — missing `game_uuid` is 404 (and `open_path` may omit it).
- ack/nack — missing `ids` is `[]`.

### `routes_apis/library.py`

- Watch GET+PUT share one view; `@validate_body` on GET would 422. Batch scan /
  edit / delete — partial-success envelopes.

### `routes_apis/ai_assist.py`

- `ai_config` — GET+PUT share one view; wrapping would 422 GET.
- `ai_triage` — `name` can come from `folder_id` / `folder_path`; no single
  required field.
- `ai_doctor_notes` — all-optional context bag.

### `routes_apis/user.py`

- `set_game_status` — empty `status` is a valid clear; unknown values stay
  400 from the view.

### `routes_apis/layouts.py`

- `layouts_detail_put` / `layouts_detail_mine_put` — pass the whole JSON bag
  through.

### `routes_apis/discover.py`

- Member pin/hide PUT shares a view with GET. Wrapping would 422 GET.

### `routes_apis/account.py`

- `create_account_invite` — `email` is optional; `{}` is a valid create.
- Avatar upload is multipart, not JSON.

### `routes_apis/collections.py`

- `update_collection` — empty `name` is refused only when that key is
  present.

### `routes_apis/acquire.py`

- `acquire_search` — `q` is a query argument, not JSON.

### `routes_apis/game_servers.py`

- `update_game_server` — empty `display_name` is refused only when that key is
  present.

### `routes_apis/patch_catalog.py`

- `patch_catalog_search` — `q` / `game_uuid` are query arguments, not JSON.

### `routes_apis/providers.py`

- Search routes — `q` is a query argument, not JSON.

### Other JSON bodies left on purpose

- `routes_apis/social.py` friends POST — a missing username is an **opaque
  success**.
- `routes_apis/rtc.py` — every field optional with defaults.
- `routes_apis/assists.py` PUT — every field optional.
- `routes_apis/locale.py` — also reads `request.form`.
- `routes_apis/notifications.py` — all-optional toggles.
- `routes_apis/download.py` — JSON + query args.
- `routes_apis/imports_playnite.py` — file or JSON.
- `routes_apis/game_mods_api.py` create — all fields optional.
- `routes_apis/licensed_catalog.py` refresh / `reference_sets.py` rehash —
  also `request.form`.
- GET+PUT sharing one view: `remote_play`, `ambient_lighting`,
  `challenge_solver`, `loading_icons`, `metadata_providers`, `scan_match`
  config.

### `routes_admin_ext/system.py`

- `update_discovery_section_schedule` / `update_discovery_section_pin` —
  all-optional bags.
- `system_reset_plan_or_perform` — rejection carries `valid_scopes` extra.

### `routes_admin_ext/game_delete.py`

- `delete_folder` — missing `folder_path` is 400 with `body_status='error'`.

### `routes_admin_ext/images.py`

- Batch search/apply, auto-pick, generate-batch — optional bags /
  partial-success.

### `routes_admin_ext/art_studio.py`

- Stock generate, apply-batch, system-marks generate — optional bags
  (`ids` / `game_uuids` / `themes` may be absent). They still share
  `_json_body()`.

### `routes_admin_ext` leftovers (settings / attract / library delete)

- `settings.py` / `attract_mode.py` — pass-through bags / "no data provided".
- `library_delete.py` — JSON + form + query; `body_status='error'` extras.

### `routes_arr.py`

- `arr_module_flag` / `arr_config` / `arr_indexers` / `arr_indexer_one` —
  GET+PUT share a view.
- `arr_indexers_bulk` — JSON or raw text.
- `arr_hardlink_apply` — `proposals` list *or* `library_dest_dir`.
- `arr_indexers_enable_presets` — `preset_ids` optional (empty list is valid).

## Follow-up backlog

`request.get_json(` still hand-rolled across `oneirodex/` (AST census
2026-09-12, `scripts/get_json_lint.py`; docstring examples are not counted):

| Area | Sites | Files |
|---|---|---|
| `routes_apis/` | 81 | 35 |
| `routes_admin_ext/` | 14 | 7 |
| rest of `oneirodex/` | 8 | 2 |
| **total** | **103** | **44** |

`utils/validation.py` (1, the shared `_json_object` reader) is the decorator
helper, not a wrap candidate. `routes_arr.py` (7 remaining) is the other
rest-of-package file.

Highest-count files still to do, roughly in priority order:

- `routes_apis/scan.py` (11; since the H-D.4 split: `scan.py` 2 · `scan_unmatched.py` 2 · `scan_unmatched_edit.py` 7) — **read on 2026-09-17, and not the batch
  candidates this line used to claim.** Every one of the eleven is one of the
  shapes the flat helper cannot express without lying: dual-input
  (`start_library_scan` / `refresh_all_libraries` take `library_uuid`,
  `force_parallel`, `queue_policy` from JSON **or** form **or** query, in that
  order); all-optional bags (`backfill_suggested_kind` — `dry_run`, `limit`;
  `bad_match` — `reason` may legitimately be absent to *clear*); or the
  unmatched batch family, which goes through `_parse_batch_ids` accepting
  `ids` **or** `items:[{id}]`, layers per-route alias keys on top
  (`item_kind`/`content_kind`/`kind`; `search_name`/`display_name`/`name`), and
  reports per-id `results`, not `updated`/`skipped`/`errors`. The theme JS
  (`admin_manage_scanjobs.js`) displays those routes' 400 `error` strings
  verbatim, so a 422 here is a visible contract change for no presence/type
  guard the view does not already have. **Leave this file at 11.** If a
  bespoke validator for the `ids|items` shape ever lands, revisit the batch
  five; the other six stay as they are.
- `routes_apis/game.py` (6 remaining; since the H-D.4 split: `game_batch.py` 4 · `game.py` 2) — the other batch routes above;
  `move_game_to_library` needs the bespoke-message validator.
- `routes_arr.py` (7 remaining) — GET+PUT, bulk text, dual-input apply.
- `routes_apis/library_tools.py` (5 remaining — propose/import dual-input,
  rename 404, Steam backfill).
- `routes_admin_ext/system.py` (3 remaining) — schedule/pin bags, reset extras.
- `routes_admin_ext/images.py` (4 remaining) — batch optional bags.
- `routes_apis/quality_stats.py` (3 remaining), `routes_apis/client.py` (4),
  `routes_apis/chat_spaces_api.py` (4), `routes_apis/chat.py` (4),
  `routes_apis/library.py` (4), `routes_apis/ownership.py` (2).
- `routes_apis/emulator_cheats.py` (3 remaining), `routes_apis/ai_assist.py`
  (3 remaining), `routes_apis/system.py` (3), `routes_apis/game_mods_api.py`
  (3).
- `routes_admin_ext/art_studio.py` (1 helper, still used by stock/batch/marks).
- long tail of 1–2-site files (GET+PUT config, all-optional, dual-input).

Named-field JSON with a real presence/type guard is exhausted on the flat
helper. Next wrap candidates on the companion: remaining `game.py` batch
routes, leftover `images.py` batch, leftover `library_tools` / `chat` /
`quality_stats` pass-through bags.

Do **not** attempt a single sweep. Each file: model → decorate → delete guards
→ run that file's tests → confirm the happy-path body is unchanged.

### Nice-to-have infra

- `@validate_batch_body` — **landed**. Same 422 as `@validate_body` plus
  `updated` / `skipped` / `errors` / optional `limit`.
- `scripts/get_json_lint.py` — **landed**. Per-file `request.get_json`
  ratchet on the `print_lint` model; CI runs it next to the print ratchet.
