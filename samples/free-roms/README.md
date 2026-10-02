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
```

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
