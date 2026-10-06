# Free / open-source sample ROMs

Legal **sample** ROMs for Oneirodex browser play and desktop companion smoke tests.

## Rules

| Allowed | Not allowed |
|---|---|
| Freely licensed (MIT, CC0, etc.) | Commercial game dumps |
| Public-domain | Warez / “ROM sites” |
| Author-redistributable test/homebrew with a clear URL | Anything whose redistribution right is unclear |

**Binaries are gitignored.** This tree only tracks `README.md` and `manifest.yaml`. Operators (or CI) run the fetch script to download into `library/`.

## Fetch

From the repo root (Python 3.9+, stdlib only — no extra packages):

```bash
python scripts/fetch-free-roms.py
```

Options:

```bash
python scripts/fetch-free-roms.py --manifest samples/free-roms/manifest.yaml
python scripts/fetch-free-roms.py --out samples/free-roms/library
python scripts/fetch-free-roms.py --dry-run
python scripts/fetch-free-roms.py --out /storage/demo-games --id nestest --id dmg-acid2
```

Use repeatable `--id` options to fetch only named manifest entries. The Blitz
public demo uses this to provision its five playable samples without fetching
unrelated smoke-test ROMs.

Each downloaded file gets a sibling `*.LICENSE.txt` with license, source, and notes from the manifest.

## Layout after fetch

```text
samples/free-roms/library/
  nes/nestest.nes
  nes/nestest.nes.LICENSE.txt
  gb/dmg-acid2.gb
  gbc/cgb-acid2.gbc
  gba/CASCADE7.gba
  genesis/genmddj-v0.17.bin
  atari2600/atari2600-4paddle-tester.a26
  snes/SuperBossGaiden.sfc
  n64/pong-oman.z64
```

Suggested Unraid / Compose library folders (gamesTheca games mount is `/storage`):

```text
/storage/nes/
/storage/gb/
/storage/gbc/
/storage/gba/
/storage/genesis/
/storage/atari2600/
/storage/snes/
/storage/n64/
```

Copy or symlink fetched files into those platform folders, then add libraries under Admin → Libraries pointing at `/storage/<platform>/`.

## Honesty

`manifest.yaml` only lists systems with a **verified** legal fetch URL. Genesis is included (MIT homebrew). GBC is included (`cgb-acid2`). SNES is included (`SuperBossGaiden.sfc`, author-released freeware). Master System / N64 and BIOS-gated systems are documented as skipped until a clear licensed URL exists — do not guess.

Optional manual (not auto-fetched): [Tobu Tobu Girl](https://tangramgames.itch.io/tobutobugirl) (MIT / CC-BY) from itch.io.

## Related docs

- [Browser & companion play](../../docs/user/browser-play.md)
- [Browser & companion play matrix](../../docs/user/browser-play.md)
- [Browser play engines](../../docs/dev/browser-play-engines.md)


## Manifest fields

`id`, `platform`, `filename`, `url`, `license`, `source`, `notes` (all one line). Optional:

- `archive: zip` — the URL is a zip; the fetcher saves the ROM inside (`member:` names it, otherwise the first file with a ROM extension).
- `sha256:` — pin the exact bytes. A file that changed upstream is refused instead of silently replacing a known-legal sample.

## Where more legal ROMs come from

Reviewed for this project (October 2026). "Used" means an entry is in the manifest; the rest are leads that need a per-ROM licence check before they go in.

| Source | Verdict |
|---|---|
| [Zophar's Domain, Public Domain ROMs](https://www.zophar.net/pdroms.html) | **Used** for Lynx and Virtual Boy. Also lists Jaguar, NGPC, NDS, GBA, Genesis, SNES, NES, N64, PCE, Apple II and more. Each ROM page links `https://www.zophar.net/download_file/<id>` (a zip). |
| [PDRoms](https://pdroms.de/) | Lead. Active catalogue of free homebrew for ~30 systems (Master System, Game Gear, MSX, ZX Spectrum, C64, Amiga, 32X …) with a page and licence note per game. Read each licence; some entries say AI-assisted. |
| [c-sp/game-boy-test-roms](https://github.com/c-sp/game-boy-test-roms) | Lead for GB/GBC. Release zips bundle test suites (Mooneye, blargg, acid2 …) under their own open licences; per-suite licence files ship in the zip. |
| [christopherpow/nes-test-roms](https://github.com/christopherpow/nes-test-roms), [nesdev emulator tests](https://www.nesdev.org/wiki/Emulator_tests) | Lead for NES: blargg and other author-released test ROMs. `nestest` is already used. |
| [mamedev.org/roms](https://www.mamedev.org/roms/) | Official, MAME-team-authorised non-commercial ROMs. ARCADE is catalog-only here (no core by default), so nothing to test yet. |
| [AtariAge homebrew](https://atariage.com/) | Per-author permission; no stable direct URLs. Use a specific author's release page if needed. |
| [Internet Arcade](https://archive.org/details/internetarcade), [MyAbandonware](https://www.myabandonware.com/) | **Not used.** They host commercial, still-copyrighted games ("abandonware" is not a licence). Do not add these. |

Browser play needs a platform whose core is installed and whose firmware is not required: Lynx, Virtual Boy, NES, SNES, GB/GBC/GBA, Genesis, 2600, N64 qualify; NDS, PSX, Saturn, 3DO and the Neo Geo CD need BIOS files Oneirodex never ships.
