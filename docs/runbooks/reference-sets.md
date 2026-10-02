# ROM reference sets (No-Intro / Redump DAT)

> **Doc status:** Active

Oneirodex can report **set completeness** per library platform + region after you upload a DAT you obtained yourself. The app does **not** ship or download copyrighted DAT files.

Related: [library-and-systems.md](../user/library-and-systems.md)

## What it measures

For a given `LibraryPlatform` (e.g. `NES`) and region (`USA`, `EUR`, `JPN`, `BRA`, `KOR`, `AUS`, `GBR`, `FRA`, `DEU`, `ESP`, `CHN`, `WORLD`, `OTHER`):

```
owned / total · percent
```

**Match v1** compares normalized titles (and ROM path basenames) to DAT entry names. Region tags like `(USA)`, dump tags like `[!]`, and simple revisions are stripped before matching. **Match v2** also compares CRC/MD5/SHA1 when library files have been hashed (scan or admin rehash).

## Obtain a DAT

1. Get a No-Intro (cartridge) or Redump (optical) `.dat` from the project’s official channels.
2. Prefer the regional DAT that matches the set you care about (e.g. USA NES).
3. Do not redistribute DAT files via Oneirodex images or git.

## Upload

Admin → Integrations → **ROM reference sets (DAT)** (`/admin/reference_sets`), or Settings hub card.

| Field | Notes |
|---|---|
| Library platform | Same enum as Systems (`NES`, `SNES`, …) |
| Region | `USA` `EUR` `JPN` `BRA` `KOR` `AUS` `GBR` `FRA` `DEU` `ESP` `CHN` `WORLD` `OTHER`. `PAL` still stores as `EUR`. France/Germany/Spain/UK are for a regional DAT you upload — they are not IGDB `release_dates.region` values. |
| Source | `nointro` / `redump` / `tosec` / `mame` / `other` |
| File | XML `datafile` (No-Intro, Redump, TOSEC, MAME `-listxml`, MAME softlist `softwarelist`) or ClrMamePro text `.dat` |

**TOSEC and MAME (INSP-34):** a TOSEC set for a home computer (`AMIGA`, `C64`, `ZX_SPECTRUM`, `CPC`, …) uploads like any other — its `(1991)(Publisher)(EU)[cr Group]` groups are stripped by the same title peel the scanner uses, so two dumps of one game collapse onto one title; pick region **WORLD** unless the set is region-split. A MAME `-listxml` or softlist for **ARCADE** (no `MAME` platform — the arcade shelf *is* the platform) is titled by each machine's `<description>` (*Pac-Man (Midway)*), not its short set name (`pacman`); the first `<rom>` under the machine or its `<part>/<dataarea>` carries the hashes. A CRC shared by several machines (clone sets reusing a ROM) is *ambiguous* for identify and never auto-creates a game.

**One game, one ROM (INSP-5):** the parser keeps one row per title. When a DAT lists the same title for several regions, the row kept is the household's preferred region (USA → EUR → JPN → … → WORLD → OTHER), not whichever the file listed first. When a DAT carries parent/clone data (`cloneof`, MAME and No-Intro P/C sets), the clone's parent is stored on the entry and **set completion counts parents only** — each game once. A dump the DAT marks as a clone of a title already in the library shows *Reference DAT lists this dump as a clone of a game already in the library* on its Duplicate row (`clone_of` names the parent set) — advisory; nothing is marked or deleted on it.

Uploading the same platform+region **replaces** the previous set.

## Repair preview (dry run)

**INSP-24.** Set completion says what is missing; the repair preview on the same admin page says what the set disagrees with among the files you *do* own. Pick a platform (and one region, or all its sets), click **Preview repairs**, and read four buckets:

| Bucket | Meaning | What you might do |
|---|---|---|
| **Hash matches, name differs** | The dump is exactly a set entry; the filename is not the set's name. | Rename by hand, or leave it — the catalogue already knows what it is. Never proposed for a `mame` set, whose files are named by machine short name the entry does not keep. |
| **Name matches, hash differs** | The filename is a set title; the bytes are not that entry. | A bad dump, another revision, a header the set strips, or an overdump. Compare CRCs; re-dump or accept. |
| **Clone-named files** | The file is a *clone* entry (parent/clone DATs), with whether the parent is owned. | Usually nothing — 1G1R completion already counts the parent once. |
| **Not in the set** | Neither hash nor name is in the set. | Homebrew, a hack, a region the set does not cover — or the wrong DAT for the shelf. |

Files that were never hashed and match a name are counted (*name-only*) but not listed — run **Rehash platform** first. Each bucket shows up to 200 rows (`limit` on the API, max 2000) with a *Showing the first N of M* line when truncated. It is a **report only**: nothing is renamed, moved or marked, on disk or in the catalogue.

```bash
curl -sS -b cookies.txt -H "Content-Type: application/json" -H "X-CSRFToken: $CSRF"   -d '{"library_platform":"NES","region":"USA","limit":50}'   "$BASE/api/reference-sets/repair-preview" | jq '.counts, .verified, .rename_candidates[:3]'
```

**Systems hub heatmap:** with `include_completion=1`, `/api/library_platforms` returns preferred `set_completion` plus `set_completion_regions` (all uploaded regions). The Systems page shows color chips per region when more than one DAT is present.

API (admin):

```bash
curl -X POST -b cookies.txt \
  -F "library_platform=NES" -F "region=USA" -F "source=nointro" \
  -F "file=@Nintendo - Nintendo Entertainment System (USA).dat" \
  "$BASE/api/reference-sets"
```

## Member UX

- **Systems** tiles show `owned / total · percent (REGION)` when a set exists.
- **Missing** opens `/systems/completion?library_platform=NES&region=USA` with a wishlist button per missing title.
- **Catalog** opens `/systems/catalog?library_platform=NES` — IGDB regional title counts from a cache an admin refreshes (one platform per click) on this same page. Empty cache is not “zero games ever made.” Native PC libraries are refused. Identify also fills cache rows when IGDB returns `release_dates`.

```bash
curl -sS -b cookies.txt \
  "$BASE/api/set-completion?library_platform=NES&region=USA" | jq '.owned, .total, .missing_count'

curl -sS -b cookies.txt \
  "$BASE/api/licensed-catalog?library_platform=NES" | jq '.unique_titles, .empty, .by_region[:3]'
```

## Honesty limits

- Title match can false-positive (shared names) or miss (IGDB-renamed library titles vs No-Intro names).
- **Hash match** (CRC/MD5/SHA1) wins when both the DAT entry and the library file have hashes. New scans hash single-file ROM paths automatically; use **Rehash platform** on the admin page (or `POST /api/reference-sets/rehash`) for existing libraries.
- **First-scan identify:** a **unique** hash hit against uploaded DATs for the library platform can auto-create a custom Game after IGDB miss (before TheGamesDB propose). Ambiguous hashes and title-only DAT names never auto-import.
- Hashes prefer the on-disk file (or the single ROM-like file inside a folder). For **zip/7z/rar**, when the outer archive digest misses DAT, Oneirodex may open the archive and hash **inner** primary dump candidate(s) (`DAT_HASH_INNER_ARCHIVE`, default ON; set `0` to disable). Exactly one unique DAT title identifies; zero or multiple distinct titles → skip (no invent). Multi-disc / cue+bin / overcrowded set archives stay skip-safe.
- Home-brew / unlicensed / proto entries may appear in some DATs — filter upstream if you want “retail only.”
- PC Windows / store libraries are a poor fit; this feature targets ROM console libraries.
- **Licensed catalog** is a separate IGDB cache (main games, `category = 0`). It does not paste Wikipedia totals into the product. Refresh is offered for every `LibraryPlatform` with a confirmed IGDB `platforms.id` except native PC. CreatiVision, Adventure Vision, Studio II, Action Max, Daphne, and Pinball have no confirmed id — they stay off that dropdown. Identify filters the same map (Game Boy Color is IGDB 22). Pico is IGDB **339**.

## Follow-ups

- Multi-region heatmap on Systems.
- Full Ops upload matrix prose (per-leaf DAT sets) — Docs/Ops after live Unraid upload.

## Related: legal sample ROMs (not DAT)

For emulator smoke tests with **freely licensed** homebrew/test ROMs (never commercial dumps), see [samples/free-roms/](../../samples/free-roms/README.md) and `python scripts/fetch-free-roms.py`.
