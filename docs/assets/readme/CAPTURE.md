# Capture (README / docs media)

Every screenshot, poster, banner and how-to clip under `docs/assets/readme/`
and `docs/media/` is produced by four scripts against a **throwaway local
instance**. Nothing here is a mock-up: if a surface cannot be photographed
honestly it is skipped and the run says so.

| Script | Produces |
|---|---|
| [`scripts/serve_capture.py`](../../../scripts/serve_capture.py) | the instance: scratch DB `oneirodexcapture`, `.env.capture.local`, admin `admin` / member `mira`, five legal ROMs, Art-studio covers, two-voice chat history, uvicorn on `:5006` |
| [`scripts/capture_docs_media.py`](../../../scripts/capture_docs_media.py) | stills → `docs/media/screenshots/*.png`, README slots → `docs/assets/readme/screenshot-*.png` + `command-palette.png`; `pulse.json` / `awake.json` |
| [`scripts/capture_howto_videos.py`](../../../scripts/capture_howto_videos.py) | narrated clips → `docs/media/video/howto/howto-*.mp4` + `.vtt` + poster `.png`, `index.json`, and that folder's `README.md` with transcripts |
| [`scripts/render_readme_art.py`](../../../scripts/render_readme_art.py) | `hero-banner.png` (Discover framed on the theme background), `h-*.svg` section headers, `card-*.svg` feature cards, `poster-*.png` video tiles — all from the theme tokens and the shared rail icons |

## Recipe

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
