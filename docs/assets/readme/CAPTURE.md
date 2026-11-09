# Capture (README / docs media)

> **Doc status:** Active

Every screenshot, poster, banner and how-to clip under `docs/assets/readme/`
and `docs/media/` is produced by four scripts against a **throwaway local
instance**. Nothing here is a mock-up: if a surface cannot be photographed
honestly it is skipped and the run says so.

For a focused parity fix, a screenshot may also come from an isolated local
staging image when the dedicated capture database is unavailable. Record the
backend image and frontend bundle identity in the private evidence; verify the
settings are empty or synthetic and mask any non-empty credential controls
before copying a screenshot into `docs/media/`. This exception does not refresh
the README product slots unless a matching slot is intentionally replaced.

Listing available stills with `python scripts/capture_docs_media.py --list` does
not require Playwright or a running capture server. Actual screenshot capture
still requires Playwright Chromium and the isolated populated instance below.

| Script | Produces |
|---|---|
| [`scripts/serve_capture.py`](../../../scripts/serve_capture.py) | the instance: scratch DB `oneirodexcapture`, `.env.capture.local`, admin `admin` / member `mira`, five legal ROMs, Art-studio covers, two-voice chat history, uvicorn on `:5006` |
| [`scripts/capture_docs_media.py`](../../../scripts/capture_docs_media.py) | stills → `docs/media/screenshots/*.png`, README slots → `docs/assets/readme/screenshot-*.png` + `command-palette.png`; `pulse.json` / `awake.json` |
| [`scripts/capture_howto_videos.py`](../../../scripts/capture_howto_videos.py) | narrated clips → `docs/media/video/howto/howto-*.mp4` + `.vtt` + poster `.png`, `index.json`, and that folder's `README.md` with transcripts |
| [`scripts/render_readme_art.py`](../../../scripts/render_readme_art.py) | `hero-banner.png` (Discover framed on the theme background), `h-*.svg` section headers, `card-*.svg` feature cards, `poster-*.png` video tiles — all from the theme tokens and the shared rail icons |

## Recipe

**2026-11-07 focused account-session capture:** the populated local capture
instance was rebuilt from the current member bundle with background workers
and external integrations disabled. Authenticated Playwright capture of
`/tokens` shows browser-session dates and current/other/all-device controls;
the image is `docs/media/screenshots/api-tokens.png`. The same isolated account
exercised missing-CSRF rejection, single-session revocation and all-device
revocation. No README slot depicts this page, so README images were not replaced.
The capture database remained a disposable local database and was not used as
Alembic-head evidence after startup reported its pre-existing baseline warning.

**2026-10-30 scan workspace source-overlay capture:** rebuilt admin-app and admin-pilot bundles from the corrected source, then installed them before startup in an isolated current R1594 image clone. Paired read-only screenshots against official v1.1.8 and current at 1440x1000 and 390x844 confirm Automatic scan and Manual identify together, with Scan jobs separate and no horizontal overflow, page errors, failed local requests or external requests. No scan actions ran; cloned databases, containers, proxies and the internal network were removed. Evidence: `.artifacts/parity-v1.1.8/scan-workspace-unification-r1596.json` and `.artifacts/parity-v1.1.8/scan-workspace-visual-r1596.json`. No README product slot depicts this route, so README images were not replaced.

**2026-11-05 admin scan navigation review:** rebuilt admin-app and admin-pilot from the local source and installed their bundle contents into isolated `oneirodex:parity-r1776-focus-fixed-v2` staging before restart. Authenticated replay covers Auto, Manual, Scan Jobs and Unmatched at seven widths (28 checks), including keyboard focus reveal and separate horizontal action/nav rows; no scan action ran. Fixtures were synthetic. Evidence and captures: `.artifacts/parity-v1.1.8/scan-ux-review-20261104/r1778/`. No README product slot depicts this route, so README images were not replaced.

**2026-10-30 IGDB surface fix:** `admin-igdb-settings.png` was refreshed from the isolated current staging image after IGDB adopted the shared admin panel surface. The capture records the exact backend and frontend bundle in private evidence `.artifacts/parity-v1.1.8/igdb-panel-r1437/evidence.json`; both viewports had no credential values, so the screenshot shows the empty fields without masks. The temporary bundle was restored and `/awake` returned 200. The dedicated capture DB was not available on this host. No README slot was changed.

**Targeted admin refresh:** 2026-10-26 — `admin-smtp-settings.png` and `admin-igdb-settings.png` were refreshed from exact-image current captures after settings action-label, order, sizing, field-label casing, and accessibility-name parity changes. The scan workspace was separately replayed against v1.1.8/current R1210 at desktop and mobile; its paired screenshots and route evidence are in `.artifacts/parity-v1.1.8/scan-workspace-r1213-exact.json`. Admin Discovery Sections was also recaptured with synthetic shelves at desktop and mobile against the same pinned images; those paired QA screenshots are in `.artifacts/parity-v1.1.8/discovery-admin-r1217-exact.json`. The Admin help direct-entry/refresh path was rechecked on those images, with its paired screenshots in `.artifacts/parity-v1.1.8/admin-help-r1218-exact.json`. The admin navigation/settings transition replay is recorded in `.artifacts/parity-v1.1.8/admin-navigation-r1219-exact.json`; QA screenshots there also did not replace README media. The Discover first/last edge-wrap replay against the exact image pair is recorded at `.artifacts/parity-v1.1.8/discover-wrap-parity-r1220-b7b6e101.json`, also outside the README media slots. Member dropdown hover contrast was refreshed on the exact image pair, with QA captures in `.artifacts/parity-v1.1.8/member-dropdown-hover-r1221-exact.json`; it did not replace README media. Discover mobile touch wrap was checked at 390px on the exact image pair; current wrap and the legacy rail-overlay limit are recorded with QA screenshots in `.artifacts/parity-v1.1.8/discover-wrap-parity-r1222-7ed31f16.json`. These were focused captures, not a rerun of all 55 surfaces.

**Focused compatibility-route QA:** 2026-10-31 — the retired `/playromtest` route was captured against exact local v1.1.8 and current R1675 images at desktop and mobile widths for R1711–R1714. The current source overlay mounted the rebuilt member bundle read-only. The empty synthetic Discover state was not copied into README product slots; no slot depicts this compatibility URL. Paired screenshots and image/network/cleanup evidence: `.artifacts/parity-v1.1.8/playromtest-shell-toast-paired-r1714.json` and its adjacent R1711–R1713 artifacts.

**Latest full still capture:** 2026-10-17 — all 55 member/admin surfaces passed
the health gate against the throwaway `oneirodexcapture` instance. README
screenshot slots were refreshed, then the hero, section art, feature cards,
and how-to poster tiles were regenerated. How-to clips and narration were not
changed; clips were last generated 2026-10-14. Screenshots and README slot
copies use atomic replacement with retries so a transient file-write error
preserves the last good image.

The Discover screenshot selects **New & updated**, which uses the seeded local
game artwork and avoids provider-dependent store images that are unavailable
in the offline capture environment.

```bash
# 0. Build what will be photographed — a stale dist silently captures old UI.
npm ci
(cd frontend/api-client && npm run build)
(cd frontend/member-app && npm run build)
(cd frontend/admin-app  && npm run build)

# 1. Sample ROMs (once): python scripts/fetch-free-roms.py  → data/games-capture/

# 2. Bring the instance up (idempotent; --reset drops the scratch DB first).
python scripts/serve_capture.py

# 3. In another shell:
python scripts/capture_docs_media.py          # stills; exit 3 = something was skipped
python scripts/capture_howto_videos.py        # narrated clips; a subset by name works
python scripts/render_readme_art.py           # hero, headers, cards, poster tiles
```

Requirements beyond `requirements-dev.txt`: Playwright Chromium, `edge-tts`
(Microsoft neural voices, network), `imageio-ffmpeg` (bundled ffmpeg with
libx264 / aac). Voice: `CAPTURE_VOICE` (default `en-US-AndrewMultilingualNeural`).
Credentials: `CAPTURE_USER` / `CAPTURE_PASS` (default `admin` / `CaptureAdmin1!`).

Never point capture at the real deploy `.env` — its paths are container-side
and will not resolve on the host. `serve_capture.py` writes its own gitignored
`.env.capture.local` with every outbound integration off, so capture never
hits a store, an AI endpoint or the core CDN.

## What the README uses

| Slot | Source | Notes |
|---|---|---|
| `hero-banner.png` | `screenshot-discover.png` composited by `render_readme_art.py` | real pixels in a frame on the token background |
| `screenshot-library.png` | `/library`, tile slider pushed to 80 % | |
| `screenshot-filters.png` | `/library` with Filters open | |
| `screenshot-game.png` | first tile's game page | `game-details-full.png` in media is the full page |
| `screenshot-discover.png` | `/discover` | |
| `screenshot-systems.png` | `/systems` | |
| `screenshot-chat.png` | Chat slide-out, expanded | two-author history |
| `screenshot-friends.png` | Friends dock | |
| `screenshot-big-picture.png` | `/big-picture` | |
| `screenshot-preferences.png` | account menu → Preferences (modal) | `/settings_panel` is a fragment, not a page |
| `screenshot-admin-ops.png` · `screenshot-admin-libraries.png` · `screenshot-art-studio.png` | admin surfaces | Ops waits for the LiveKit tile; every other admin page is in `docs/media/screenshots/` |
| `admin-smtp-settings.png` · `admin-smtp-setup-help.png` · `admin-igdb-settings.png` | SMTP and IGDB settings forms, with SMTP setup help expanded | Credentials are synthetic in the capture fixture; provider calls are disabled |
| `command-palette.png` | Ctrl-K on `/library` | |
| `poster-*.png` | the clip's poster frame + play badge + title strip | one per how-to |

Retired for good: `hero-banner.jpg`, `screenshot-*.jpg` — illustrative mock
previews from before capture existed. Do not restore them.

## Gates

- **Health gate** — every still and the end of every clip passes
  `page_is_healthy()`: no error page, not near-empty, and the theme stylesheet
  actually loaded (a page can have every word present and still be unstyled).
  A failing surface is skipped, the existing file is left untouched, and the
  stills run exits **3**. Treat non-zero as "pixels are stale", never as "done".
- **Required steps** — a clip's subject step is `required`; if the UI cannot
  do it, no file is written. Optional steps whose affordance is missing are
  dropped from picture *and* narration.
- **Global panels** — Chat and Friends survive navigation; both capture
  scripts close them before every surface (`close_overlays`). A page was once
  shot blank behind an open chat panel.

## Known gaps in the sample data

Five ROMs, no store keys, cores not fetched, LiveKit off. So: no related
media, screenshots or trailers on any title; browser play is shown but not
pressed; Voice / Screenshare are shown but no session joins; the release
calendar and news are what a keyless install shows. Listed in
[howto/README.md](../../media/video/howto/README.md) so nobody re-records
expecting different footage. **Do not invent pixels** for these.

## Refresh rule (Docs owns)

Every ship pass that touches member or admin UI re-runs the three capture
scripts, then `render_readme_art.py`. The `docs-sync` skill lists this as a
checklist item; the README says "every screenshot and clip on this page is
live UI", and that sentence is the contract.

## Host notes

- Windows / Git Bash: prefix any command that takes a `/route` argument with
  `MSYS_NO_PATHCONV=1`, and set `PYTHONIOENCODING=utf-8` (the app prints an
  emoji on startup).
- The login page carries a hidden "Delete Game" submit button first in the
  DOM; the scripts press Enter in the password field rather than clicking
  the first submit.
- `pydantic-core` on a shared interpreter drifts to 2.49.0; `create_app()`
  refuses to import until it is back on the pinned 2.46.5.
- Running the clip recorder and the stills capture at the same time against
  the single-worker instance makes both time out. One at a time.
