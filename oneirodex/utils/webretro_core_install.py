"""Provision the WebRetro libretro cores at first boot.

The cores used to be committed — 71MB of WASM across 24 cores — despite
``cores/README.md`` describing the directory as "operator-owned" and
``tests/test_webretro_cores.py`` opening with "no multi-MB WASM in repo". Both
had it right and the tree did not.

They are removed for licence reasons, not size. The set carries GPL-2.0,
GPL-3.0 and MPL-2.0 terms, and ``snes9x`` and ``genesis_plus_gx`` add custom
clauses restricting commercial distribution. Shipping GPL binaries obliges the
distributor to ship the licence text and a Corresponding Source offer with them,
and none of that was present. Fetching them onto the operator's own box at boot
makes the operator the party doing the provisioning, which is the shape
``scripts/fetch-webretro-cores.sh`` already assumed.

This is the same contract ``font_install`` uses for the OFL faces, with one
deliberate difference: fonts ship bundled and only fall back to the network,
because we may redistribute them. These we may not, so the network is the only
path — and ``FETCH_WEBRETRO_CORES_ON_BOOT=false`` plus ``--from-dir`` is the
air-gapped answer.

Honesty note: browser play reports what it can run from
``platform.WEBRETR_INSTALLED_CORES``. That set stays accurate for a normal
install because the fetch runs by default, so :func:`missing_cores` is what the
boot hook warns on when it does not.
"""

from __future__ import annotations

import os
from pathlib import Path

#: jsDelivr mirror of BinBashBanana/webretro at the version the core set matches.
#: Pinned, not floating: a core silently changing under an install is the kind
#: of thing that turns into "browser play broke and nothing changed".
WEBRETRO_VERSION = '6.5'
CDN = f'https://cdn.jsdelivr.net/gh/BinBashBanana/webretro@{WEBRETRO_VERSION}/cores'

#: Each core is a ``.js`` loader plus its ``.wasm``. One without the other is
#: not a working core, so they are fetched and validated as a pair.
CORE_SUFFIXES = ('_libretro.js', '_libretro.wasm')

#: Bytes below which a response is assumed to be an error page rather than a
#: core. The smallest real core is comfortably over 100KB.
MIN_CORE_BYTES = 32 * 1024


def default_cores_dir() -> Path:
    from oneirodex.utils.webretro_cores import default_cores_dir as _dir

    return _dir()


def default_core_ids() -> frozenset[str]:
    """The set the fetch installs — the same one browser play advertises."""
    from oneirodex import platform as plat

    return frozenset(getattr(plat, 'WEBRETR_INSTALLED_CORES', ()) or ())


def missing_cores(cores_dir: str | Path | None = None) -> frozenset[str]:
    """Default cores without both halves present on disk."""
    from oneirodex.utils.webretro_cores import core_dirs

    roots = core_dirs(cores_dir)

    def _complete(root: Path, core_id: str) -> bool:
        for suffix in CORE_SUFFIXES:
            path = root / f'{core_id}{suffix}'
            if not path.is_file() or path.stat().st_size < MIN_CORE_BYTES:
                return False
        return True

    return frozenset(c for c in default_core_ids() if not any(_complete(r, c) for r in roots))


def _fetch(url: str) -> bytes:
    # Through safe_get so the boot fetch obeys the same outbound policy as
    # everything else, redirects included.
    from oneirodex.utils.http_safe import safe_get
    from oneirodex.utils.security import validate_user_outbound_http_url

    response = safe_get(url, validator=validate_user_outbound_http_url, timeout=60)
    response.raise_for_status()
    return response.content


def install_core(core_id: str, cores_dir: str | Path | None = None) -> bool:
    """Fetch one core pair. Returns True when both halves land.

    Written to a temp name and moved into place, so an interrupted fetch cannot
    leave a half-file that :func:`missing_cores` would then count as present.
    """
    root = Path(cores_dir) if cores_dir else default_cores_dir()
    root.mkdir(parents=True, exist_ok=True)

    staged: list[tuple[Path, Path]] = []
    try:
        for suffix in CORE_SUFFIXES:
            name = f'{core_id}{suffix}'
            payload = _fetch(f'{CDN}/{name}')
            if len(payload) < MIN_CORE_BYTES:
                raise ValueError(f'{name} was {len(payload)} bytes — not a core')
            tmp = root / f'.{name}.part'
            tmp.write_bytes(payload)
            staged.append((tmp, root / name))
    except Exception:
        for tmp, _dest in staged:
            tmp.unlink(missing_ok=True)
        raise

    for tmp, dest in staged:
        os.replace(tmp, dest)
    return True


def install_missing_cores(cores_dir: str | Path | None = None) -> tuple[int, list[str]]:
    """Fetch every missing default core. Returns (installed, failed_ids).

    One core failing must not abandon the other twenty-three — a partial set is
    a working emulator for the platforms it covers.
    """
    installed = 0
    failed: list[str] = []
    for core_id in sorted(missing_cores(cores_dir)):
        try:
            install_core(core_id, cores_dir)
            installed += 1
        except Exception:
            failed.append(core_id)
    return installed, failed
