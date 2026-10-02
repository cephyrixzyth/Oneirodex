"""WebRetro WASM core discovery (operator-vendored cores on disk)."""

from __future__ import annotations

from pathlib import Path

from oneirodex.utils.library_paths import static_write_dir

# Cores operators may drop later — not shipped in the default image.
DEFERRED_BROWSER_CORES: dict[str, dict] = {
    'mednafen_pce_fast': {
        'platforms': ['PCE'],
        'label': 'PC Engine / TurboGrafx (mednafen_pce_fast)',
    },
    'mednafen_supergrafx': {
        'platforms': ['PCE'],
        'label': 'SuperGrafx (mednafen_supergrafx)',
    },
    'vice_x64': {
        'platforms': ['VICE_X64SC', 'VICE_X128', 'VICE_XVIC', 'VICE_XPLUS4', 'VICE_XPET'],
        'label': 'Commodore (vice_x64)',
    },
    'dosbox_pure': {
        'platforms': ['PCDOS'],
        'label': 'DOS (dosbox_pure)',
        'flag': 'ENABLE_PCDOS_BROWSER',
    },
    'dosbox': {
        'platforms': ['PCDOS'],
        'label': 'DOS (dosbox)',
        'flag': 'ENABLE_PCDOS_BROWSER',
    },
}


_PACKAGE_ROOT = Path(__file__).resolve().parent.parent


def default_cores_dir() -> Path:
    """Where cores are fetched to; served at /static/vendor/webretro/cores/.

    Inside the install normally. When the library has been moved to a data
    folder (a standalone install) this is ``<library>/static-overrides/…`` and
    the static handlers serve it at the same URL.
    """
    return static_write_dir('vendor', 'webretro', 'cores', package_root=_PACKAGE_ROOT)


def shipped_cores_dir() -> Path:
    """Cores that came with the install."""
    return _PACKAGE_ROOT / 'static' / 'vendor' / 'webretro' / 'cores'


def core_dirs(cores_dir: str | Path | None = None) -> list[Path]:
    """Folders a core may be found in: the fetch target, then the shipped one."""
    if cores_dir:
        return [Path(cores_dir)]
    dirs = [default_cores_dir()]
    if shipped_cores_dir() != dirs[0]:
        dirs.append(shipped_cores_dir())
    return dirs


def discover_webretro_cores(cores_dir: str | Path | None = None) -> frozenset[str]:
    """Return core IDs that have a ``*_libretro.wasm`` file on disk."""
    found: set[str] = set()
    for root in core_dirs(cores_dir):
        if not root.is_dir():
            continue
        for path in root.glob('*_libretro.wasm'):
            name = path.name[: -len('_libretro.wasm')]
            if name:
                found.add(name)
    return frozenset(found)


def get_effective_installed_cores(cores_dir: str | Path | None = None) -> frozenset[str]:
    """Shipped allowlist ∪ cores discovered on disk.

    Reads ``WEBRETR_INSTALLED_CORES`` live so tests can monkeypatch it.
    """
    from oneirodex import platform as plat

    shipped = frozenset(getattr(plat, 'WEBRETR_INSTALLED_CORES', ()) or ())
    return shipped | discover_webretro_cores(cores_dir)


def wasm_present_on_disk(core_id: str, cores_dir: str | Path | None = None) -> bool:
    return any((root / f'{core_id}_libretro.wasm').is_file() for root in core_dirs(cores_dir))


def deferred_core_status(cores_dir: str | Path | None = None) -> dict[str, dict]:
    """Operator-facing status for Wave 19 deferred WASM cores."""
    roots = core_dirs(cores_dir)
    out: dict[str, dict] = {}
    for core_id, meta in DEFERRED_BROWSER_CORES.items():
        out[core_id] = {
            **meta,
            'wasm_present': any((root / f'{core_id}_libretro.wasm').is_file() for root in roots),
            'js_present': any((root / f'{core_id}_libretro.js').is_file() for root in roots),
        }
    return out
