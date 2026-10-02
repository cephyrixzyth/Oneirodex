# RetroArch AI Service (live OCR / MT overlay)

> **Doc status:** Active

**Status:** Operator-hosted · Oneirodex hints only (`ENABLE_ROM_AI_TRANSLATE`)  
**Not:** a permanent ROM patch, browser WebRetro feature, or bundled OCR server

## What it does

RetroArch can send screenshots to a local **AI Service** endpoint for OCR + machine translation, then overlay the result. Quality is a **gist**, not a fan translation.

Supported when playing via **companion / native RetroArch**. Browser WebRetro cannot use this path.

## Operator setup

1. Run a local AI Service compatible with RetroArch (e.g. vgtranslate or a community LLM OCR server). Bind to LAN/localhost only.
2. In RetroArch: **Settings → AI Service**
   - Enable AI Service
   - Output: **Image mode** (recommended for overlays)
   - AI Service URL: your local server (Oneirodex may hint `RETROARCH_AI_SERVICE_URL`)
   - Source / target languages to match the ROM and Preferences → Preferred game language
3. In Oneirodex `.env`:
   ```bash
   ENABLE_ROM_AI_TRANSLATE=true
   RETROARCH_AI_SERVICE_URL=http://127.0.0.1:4404
   ```
4. On game details, titles that need translation and have **no** patch show a **Live translate** panel with the target-language hint.

## Companion behavior

The desktop companion logs a setup note when launching RetroArch with AI hints enabled. RetroArch stores the AI Service URL in **its own config** — Oneirodex does not invent fragile CLI flags for the service URL.

## Limits

| Constraint | Why |
|---|---|
| Overlay only | Does not rewrite the ROM or create `.bps` |
| Per-frame / hotkey | Depends on RetroArch + service latency |
| Core pixel formats | RGB565/RGB888 cores; some HW-rendered cores unsupported |
| No cloud keys in Oneirodex | Operator brings their own local service |

## Related

- [translation-patches.md](../user/translation-patches.md)
- [desktop-companion.md](../user/desktop-companion.md)
