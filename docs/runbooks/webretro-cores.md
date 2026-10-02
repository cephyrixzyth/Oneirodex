# WebRetro cores — operator vendor guide

> **Doc status:** Active

**Status (changed 2026-08-25):** the **24** WebRetro 6.5 cores are **no longer committed**. They are
fetched into this directory on first boot (`FETCH_WEBRETRO_CORES_ON_BOOT`, default on), or by the
script below. PCE / VICE / DOSBox WASM remain operator-owned as before. Companion Play works without
any of them.

**Why they left the tree.** They were 71MB of binaries carrying GPL-2.0, GPL-3.0 and MPL-2.0 terms,
with `snes9x` and `genesis_plus_gx` adding clauses that restrict commercial distribution — and no
licence text or Corresponding Source offer travelled with them. `cores/README.md` had described the
directory as "operator-owned" all along and `tests/test_webretro_cores.py` opens with "no multi-MB
WASM in repo"; the tree simply did not match. Fetching them onto the operator's own box makes the
operator the party provisioning them. Operator notes on the `snes9x` / `genesis_plus_gx`
non-commercial clauses (quotes + questions for a lawyer, **not counsel**):
[webretro-core-clauses.md](../admin/webretro-core-clauses.md).

**Air-gapped installs:** set `FETCH_WEBRETRO_CORES_ON_BOOT=false` and use `--from-dir`. Boot logs a
warning naming the missing cores rather than letting browser play fail silently.

Related: [browser-play.md](../user/browser-play.md) · [browser-play-engines.md](../dev/browser-play-engines.md) · [webretro-core-clauses.md](../admin/webretro-core-clauses.md)

## Storage path

```
oneirodex/static/vendor/webretro/cores/
  {core_id}_libretro.js
  {core_id}_libretro.wasm
```

Optional Docker bind-mount — with the cores no longer in the image, an empty mount is now simply
where the first-boot fetch writes them, provided the volume is writable:

```yaml
# docker-compose.yml (uncomment when ready)
# - "${WEBRETRO_CORES_HOST_PATH}:/app/oneirodex/static/vendor/webretro/cores"
```

## One-command fetch

```bash
# Defaults from BinBashBanana/webretro@6.5 (jsDelivr) — 24 cores
./scripts/fetch-webretro-cores.sh --defaults

# Deferred cores from your Emscripten / WebRetro pack (not on the CDN)
./scripts/fetch-webretro-cores.sh --from-dir /path/to/built/cores

# Windows
.\scripts\fetch-webretro-cores.ps1 -Defaults
.\scripts\fetch-webretro-cores.ps1 -FromDir C:\path\to\built\cores
```

You are responsible for each core’s license compliance. For `snes9x` and `genesis_plus_gx`,
start with [webretro-core-clauses.md](../admin/webretro-core-clauses.md) — that file is research
notes, not permission.

## Deferred cores (Wave 19)

| Core ID | Platforms | Extra flag |
|---|---|---|
| `mednafen_pce_fast` | PCE | none — auto browser when files present |
| `mednafen_supergrafx` | PCE (optional) | none |
| `vice_x64` | VICE / C64 family | none |
| `dosbox_pure` (preferred) or `dosbox` | PCDOS | `ENABLE_PCDOS_BROWSER=true` |

These IDs return **404** on the webretro@6.5 CDN — build via RetroArch emscripten ([pkg/emscripten README](https://github.com/libretro/RetroArch/blob/master/pkg/emscripten/README.md)) or copy from a compatible WebRetro core pack, then `--from-dir`.

## Steps (end-to-end)

1. Fetch defaults and/or copy deferred pairs into `cores/` (script above).
2. **No `base.js` edit** — Oneirodex serves `GET /api/emulator/installed-cores.js` from disk discovery; `standalone.html` loads WASM from `/static/vendor/webretro/` (not CDN).
3. Restart the app if cores live only in the image layer (bind-mounts are live).
4. Check health:
   ```bash
   curl -sS "$BASE/api/emulator/health" | jq '.deferred_cores, .installed_cores'
   curl -sS "$BASE/api/emulator/installed-cores.js"
   ```
5. For DOS only: set `ENABLE_PCDOS_BROWSER=true`.
6. Confirm Systems badge flips to **Browser** and game details shows **Play in browser** when `can_play_in_browser` is true.

## Cold start (Oneirodex embed)

Play opens `webretro.html` → iframe `standalone.html?core=&rom=&nobundle=1`.

| Optimization | Where |
|---|---|
| Local CSS/JS (no jsDelivr on boot) | `standalone.html` → `/static/vendor/webretro/assets/*` |
| Skip RetroArch asset bundle CDN storm | `nobundle=1` on the iframe URL |
| Local BIOS path | `base.js` `biosCdn` → `/static/library/bios/` (Admin upload **or** optional private host mount — [unraid-deploy.md](unraid-deploy.md#local-private-bios-mount-vs-public-upload); never ship firmware in the image) |
| Preload core JS/WASM + warm ROM cache | `webretro.html` `preloadPlayAssets()` |
| Defer cloud-save API | After `mainCompleted` + `requestIdleCallback` |
| Cache installed-cores allowlist | `GET /api/emulator/installed-cores.js` → `private, max-age=300` |

**Saves → Sync now** still works immediately once the ROM is ready; the boot pull only *offers* a state (resume bar), it never loads one unasked.

## Honesty rules

- Do **not** advertise browser Play if WASM is missing.
- Leaving deferred cores out is fine — companion / catalog modes stay accurate.
- Large DOS WASM still needs vendored cores on disk; `ENABLE_PCDOS_BROWSER` defaults **on** (see `.env.example`).

## Verify

```bash
curl -sS "$BASE/api/emulator/health" | jq '.deferred_cores, .installed_cores'
```
