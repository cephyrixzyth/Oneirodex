# Translation patches (IPS / BPS / UPS)

> **Doc status:** Active

Some ROMs ship in a region or language that does not match your preferred game language (Preferences → **Preferred game language**, default `en-US`). Oneirodex can detect No-Intro-style tags from filenames and catalog patch files in the game’s **extras** folder.

## Library filter

On Library, the **LANG** badge chip (in the left filter column) filters to titles whose ROM language is known and does **not** match your preferred game language. Unknown / unlabeled ROMs are left out of that filter. Cover badges show **LANG** on mismatch and **PATCH** when a translation patch exists in extras.

## Safety

- Keep a **backup** of the original ROM before applying any patch.
- Prefer patches from a source you trust (operator-curated URLs or your own files).
- Oneirodex does **not** scrape third-party patch databases.
- Operators may enable a **local YAML/JSON catalog** (`ENABLE_PATCH_CATALOG` + `PATCH_CATALOG_PATH`) to attach guide URLs — see [`data/patch_catalog.example.json`](../../data/patch_catalog.example.json).

## Live translate (no fan patch)

When `ENABLE_ROM_AI_TRANSLATE=true`, game details can show **Live translate (RetroArch AI)** for mismatched ROMs without patches. This is an OCR/MT **overlay** in companion/native RetroArch — not a permanent patch. Setup: [retroarch-ai-service.md](../runbooks/retroarch-ai-service.md). Browser WebRetro cannot use it.

Offline dump→rebuild is **stubbed** per system (local strategy notes).

## Apply with Flips (recommended)

[Flips](https://github.com/Alcaro/Flips) applies IPS and BPS patches on Windows / Linux / macOS.

1. Install Flips and note the binary path (`flips.exe` or `flips`).
2. Download the base ROM from Oneirodex (or use your local copy).
3. Download the `.ips` / `.bps` patch from **Translations & patches** on the game details page (or from extras).
4. Open Flips → **Apply patch** → select patch + base ROM → choose an output path.
5. Play the patched ROM; leave the original untouched.

UPS patches: use Flips if supported for your build, or another UPS-capable tool. Prefer BPS when available.

## Companion apply (optional)

When the operator sets `ENABLE_ROM_PATCH_APPLY=true` and configures `FLIPS_PATH`, the desktop companion can queue **Apply with companion** for a cataloged patch. Until that flag is on, the UI shows this how-to instead.

Companion stages files under `app_data/patches/{gameUuid}/` (ACL-safe like cheats) and invokes Flips CLI. Output is written beside the staged ROM — never overwrite the only copy of a base ROM without a backup.

## Operator: catalog patches

Place `.ips` / `.bps` / `.ups` under the game’s extras folder (same pattern as other extras). On scan, Oneirodex sets `extra_kind=translation_patch` and optional `target_language` from the filename. Optionally set `source_url` on the `GameExtra` row to a patch guide URL you host or trust.

## Related

- [Preferences & themes](preferences-themes.md) — preferred game language
- [Desktop companion](desktop-companion.md) — connect and lifecycle
- [FAQ](faq.md)
