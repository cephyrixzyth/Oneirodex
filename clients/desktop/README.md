# Oneirodex Desktop Companion

Cross-platform Tauri client (Windows · macOS · Linux) with **two build flavors** against a Oneirodex server:

| Flavor | Command | What it does |
|---|---|---|
| **Full companion** (default) | `npm run tauri:build` | **Download · Install · Update · Uninstall · Play** |
| **Thin client** | `npm run tauri:build:thin` | Connect + Open library / Friends only — **no** install pipeline |

Thin is not “coming later”: TC-2 shell is buildable today. See [thin-client.md](../../docs/user/thin-client.md).

## Stack

| Layer | Choice |
|---|---|
| Shell | [Tauri 2](https://tauri.app/) |
| UI | Vite + vanilla TypeScript |
| API | `@oneirodex/api-client` (`frontend/api-client`) |

## Prerequisites

- **Node.js** 20+ and npm
- **Rust** stable (`rustup`) — required for `tauri dev` / `tauri build`
- **Tauri system deps** — see [Tauri prerequisites](https://v2.tauri.app/start/prerequisites/) (WebView2 on Windows)

## Quick start

```bash
cd clients/desktop
npm install
npm run tauri:dev
```

This starts the Vite dev server on port **1420** and opens the Tauri window (full companion mode).

### Other commands

| Command | Purpose |
|---|---|
| `npm test` | Run Vitest unit tests (auth, lifecycle, connect, download/install helpers) |
| `npm run dev` | Vite only (browser preview; Tauri invoke calls are no-ops) |
| `npm run build` | Typecheck + production frontend bundle to `dist/` |
| `npm run build:thin` | Frontend bundle with `VITE_CLIENT_MODE=thin` |
| `npm run tauri:build` | Full companion, unsigned installer for this host (requires Rust) |
| `npm run tauri:build:thin` | Thin flavor via `src-tauri/tauri.thin.conf.json` (connect + library/Friends; no FS lifecycle ACL) |

### Installers

Bundling is on, so a build produces a real (unsigned) installer under `src-tauri/target/<target>/release/bundle/`:

| Host | Output |
|---|---|
| Windows | `.exe` (NSIS) |
| macOS | `.app` + `.dmg` |
| Linux | `.deb` + `.AppImage` |

`.msi` and `.rpm` are excluded while the version is a pre-release (`1.0.0-beta`) — both bundlers reject one. The flavors bundle under distinct product names (`Oneirodex` / `OneirodexThin`), so they no longer overwrite each other; only the **bare** `target/release/oneirodex-desktop[.exe]` path is still shared.

For all three platforms in one go, use [`scripts/build-installers.sh`](../../scripts/build-installers.sh) — [local-installers.md](../../docs/runbooks/local-installers.md).

## Auth & config persistence

1. Enter your **server base URL** (e.g. `https://oneirodex.example.com`).
2. Enter a personal **API token** (`gt_<hexprefix>_<urlsafe-secret>`; secret may include `_`/`-`) from **Account → API tokens** (or Admin). Full companion needs the **Desktop companion** preset (`read:library` + **`write:download`**). Thin uses the **Thin client** preset (no download).
3. Click **Connect** — validates via `GET /api/collections`, then loads a library preview via search.
4. Non-secret settings (base URL) are saved to app data as JSON; the API token goes to the OS credential store:

   - Windows: `%APPDATA%\com.oneirodex.desktop\config.json` (base URL only) + Windows Credential Manager (`com.oneirodex.desktop` / `api_token`)
   - macOS: `~/Library/Application Support/com.oneirodex.desktop/config.json` + Keychain
   - Linux: `~/.local/share/com.oneirodex.desktop/config.json` + Secret Service

   The credential **service** is the app's own bundle identifier, so the thin client stores under `com.oneirodex.thin` and the two flavors cannot overwrite each other's token. They previously shared the companion's service name, which meant installing thin on a companion PC replaced the companion's token with a thin-preset one that has no `write:download` — and Download/Install then failed on scope. If you had both installed before this change, re-paste the companion token once.

Legacy plaintext `token` fields in `config.json` are migrated into the secure store on next load and scrubbed from the file. `KeychainAdapter` in `src/auth.ts` is wired via `src/keychain.ts` → Tauri `secure_store_*` commands.

## Download & install pipeline

The desktop client downloads **DRM-free library files from your Oneirodex server only** (no Steam/GOG acquisition).

### On-disk layout (app data)

| Path | Purpose |
|---|---|
| `downloads/<game-uuid>.zip` | Downloaded archive from the server |
| `installs/<game-uuid>/` | Extracted game files after **Install** |
| `installs.json` | Sidecar map `{ gameUuid: { archivePath, extractPath, exePath? } }` |
| `lifecycle.json` | Local install state machine per game |

Example (Windows):

- `%APPDATA%\com.oneirodex.desktop\downloads\…`
- `%APPDATA%\com.oneirodex.desktop\installs\…`

### Server flow

1. **Initiate:** `POST /api/downloads/games/<uuid>` (Bearer token) — mirrors web `/download_game/<uuid>` and returns `{ download_id, stream_url }`.
2. **Stream:** `GET /download_zip/<download_id>` with the same Bearer token — same path the web UI uses after adding a game to the download basket.
3. **Install:** extracts the local ZIP into `installs/<uuid>/` via a Rust `zip` command, shallow-searches for a likely `.exe`, and stores paths in `installs.json`.
4. **Uninstall:** deletes the extract folder (and archive by default) and transitions lifecycle state.

Progress text appears on each game card (`Downloading…`, `Extracting…`, errors).

## Lifecycle

Local install state uses `createLifecycleRegistry()` from `src/lifecycle.ts`. Each game card shows the current state and allowed actions (download / install / update / uninstall). The registry panel lists all tracked games.

On startup the desktop app hydrates the registry from app-data JSON via Tauri commands (`load_lifecycle_registry` / `save_lifecycle_registry`). State changes persist automatically.

Supported states: `not_downloaded`, `downloaded`, `installed`, `update_available`.

## Client heartbeat

While connected, the desktop companion POSTs `POST /api/client/heartbeat` every 60 seconds (see `src/heartbeat.ts`, typed through `@oneirodex/api-client`'s `device` API). Payload includes a stable `device_id`, `device_name`, `client_version`, and **`device_kind`** — `companion` here, `thin` from the thin shell. The server defaults an omitted kind to `companion`, so every client sends its own explicitly; otherwise a thin seat is indistinguishable from a companion in the Ops device list.

`client_version` is injected from `package.json` at build time (`__APP_VERSION__` in `vite.config.ts`), not hardcoded — a version bump cannot miss this surface.

The server uses recent heartbeats (5-minute TTL) to set `client_connected: true` on browse/discover/game-details responses so the web UI enables Install/Update/Uninstall actions when the companion is online.

After **two consecutive heartbeat failures**, the UI switches to **Offline**: Download / Update / apply_patch are disabled with an explanation; Play / Install / Uninstall remain available. Queued web commands are nack’d back to `pending` until the companion is reachable again.

## Friends window

**Open friends window** creates or focuses a compact bottom-right always-on-top Tauri label `social` (~360×560, work-area anchored) pointed at `{baseUrl}/social-companion`. Capability file `capabilities/social.json` grants only `core:default` (no FS / launch ACL). Main window keeps create/focus/always-on-top/close permissions so a Server URL change can recreate the webview. Friends open uses the **form Server URL** (Connect not required); companion heartbeat Offline does not block Friends.

## Project layout

```
clients/desktop/
  index.html              # Vite entry
  src/
    auth.ts               # Base URL + Bearer token store
    api.ts                # OneirodexClient wrapper
    lifecycle.ts          # Install state machine
    connection-ux.ts      # Online/offline action gating helpers
    lifecycle-store.ts    # Tauri lifecycle.json persistence
    install-store.ts      # Tauri installs.json sidecar
    paths.ts              # URL/path helpers (tested)
    download.ts           # Initiate + stream + save archive
    install.ts            # ZIP extract + lifecycle install
    uninstall.ts          # Remove local files + lifecycle
    heartbeat.ts          # POST /api/client/heartbeat scheduler (device_kind aware)
    version.ts            # __APP_VERSION__ from package.json — reported as client_version
    thin-app.ts           # Thin shell UI: connect, library/Friends webviews, thin presence
    social-window.ts      # Friends companion webview
    connect.ts            # Connection validation + library preview
    config-store.ts       # Tauri file persistence (base URL; migrates/scrubs plaintext token)
    keychain.ts           # KeychainAdapter → OS credential store
    trusted-shares.ts     # Trusted network shares editor (UNC roots `open_path` may reach)
    app.ts                # Minimal UI
  fixtures/
    server-urls.json      # Server URL -> verdict cases read by BOTH the vitest and the cargo tests
  src-tauri/
    src/lib.rs            # Config, secure_store_*, lifecycle, installs, zip extract commands
    src/trusted_shares.rs # UNC trust list matching (string-only, no filesystem probe)
    src/install_recovery.rs # Atomic registry write; snapshot / update-generation copy (never follows links)
    tauri.conf.json       # Full companion
    tauri.thin.conf.json  # Thin flavor (stripped capabilities)
    capabilities/         # default + social (full); thin-main + thin-library + social (thin)
    permissions/
```

## Tests

```bash
cd clients/desktop
npm install
npm test

# Rust side (path-traversal / zip-slip guards in src-tauri/src/lib.rs):
npm run build            # generate_context!() needs dist/ before the lib compiles
cd src-tauri
cargo fmt --all --check
cargo clippy --all-targets -- -D warnings
cargo test
```

Unit tests mock `fetch`, Tauri `invoke`, and the download initiate API — no live Oneirodex server required. Two pieces are checked from both languages so they cannot drift: `fixtures/server-urls.json` (the plain-`http://` server URL policy) is read by `src/transport-policy.test.ts` and by the `validate_server_base_url` tests in `src-tauri/src/lib.rs`, and `src/open-path.test.ts` reads `lib.rs` to compare the `NETWORK_PATH_REFUSED` message. The `rust-checks` job in `desktop-build.yml` runs `cargo fmt --check` / `clippy -D warnings` / `cargo test` on every push that touches `clients/desktop/**`, `frontend/api-client/**`, or `frontend/shared/**`.

## Out of scope (this track)

- Store publishing / Apple notarization
- Bundled torrent/debrid acquisition (BYO connectors only)
- OIDC / Authentik setup (see server runbooks separately)
- **Android APK** — spike notes only (local strategy); not built from this README
- Native OpenXR / Quest-store Oneirodex shell — headset path is browser `/vr` + Big Picture ([controllers-and-vr.md](../../docs/user/controllers-and-vr.md))

## Distribution (unsigned only)

**Product stance:** code-signing certificates will never be pursued — on any platform. Unsigned installers are the supported path for both flavors; do not set signing secrets or Apple notarization credentials.

CI (`.github/workflows/desktop-build.yml`) builds and uploads **six** unsigned artifacts — full and thin × Windows / macOS / Linux — named `oneirodex-<flavor>-<platform>`. macOS is built `--target universal-apple-darwin`, so one `.dmg` covers Apple silicon and Intel.

See [desktop-code-signing.md](../../docs/runbooks/desktop-code-signing.md) for the locked stance and [local-installers.md](../../docs/runbooks/local-installers.md) for building without CI.

## Server prerequisites

- Oneirodex server with user API token — full: `read:library` + **`write:download`**; thin: thin preset (no download)
- HTTPS recommended
