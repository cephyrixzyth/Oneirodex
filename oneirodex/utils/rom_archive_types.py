"""ROM / archive extension tables, per-platform dump suffixes, extractor
binary names and ``ArchiveRomError``.

Split out of ``rom_archive`` in the v11 cycle (H-D.4) as a pure move. Data
only; ``rom_archive`` re-exports everything callers import.
"""
from __future__ import annotations



ROM_EXTENSIONS = frozenset({
    '.nes', '.smc', '.sfc', '.n64', '.z64', '.v64', '.gb', '.gbc', '.gba',
    '.nds', '.3ds', '.cia', '.iso', '.gcm', '.rvz', '.wbfs', '.wad',
    '.cue', '.bin', '.chd', '.pce', '.ngp', '.ngc',
    '.ws', '.wsc', '.col', '.vec', '.a26', '.a52', '.a78', '.lnx', '.jag',
    '.md', '.smd', '.gen', '.sms', '.gg', '.32x', '.rom', '.fds',
    '.pbp', '.cso', '.img', '.raw', '.wav', '.gdi', '.cdi',
    '.nsp', '.xci', '.nsz', '.xcz',
    '.sg', '.sgx', '.sv', '.cpr', '.int', '.chf', '.min',
    '.wud', '.wux', '.wua', '.tzx', '.z80', '.mx1', '.mx2', '.cas', '.sna',
    '.dsk', '.st', '.stx', '.tap', '.adf', '.ipf',
    '.atr', '.xfd', '.atx', '.xex', '.dim', '.xdf', '.hdm',
    '.fdi', '.hdi', '.nhd', '.d88', '.d64', '.prg', '.crt',
})

ARCHIVE_EXTENSIONS = frozenset({'.zip', '.7z', '.rar'})

# Single-file gzip wrappers of a ROM (e.g. Adventure.nes.gz) — scanned via AllowedFileType `gz`.
GZIP_EXTENSIONS = frozenset({'.gz'})

# Advertised by scan history or mistaken drops; not extractable for WebRetro.
UNSUPPORTED_ARCHIVE_EXTENSIONS = frozenset({
    '.tar', '.tgz', '.tbz2', '.txz', '.xz', '.bz2', '.lz', '.lzma',
})

# Host binaries — Docker ships libarchive-tools (bsdtar) + p7zip-full (7z).
_EXTRACTOR_BINARIES: tuple[tuple[str, str], ...] = (
    ('7z', '7z'),
    ('7za', '7za'),
    ('bsdtar', 'bsdtar'),
    ('unrar', 'unrar'),
)

_MISSING_EXTRACTOR_HINT = (
    'Install p7zip-full (7z) and/or libarchive-tools (bsdtar) on the host '
    '(the Oneirodex Docker image already includes both), ensure they are on PATH, '
    'or re-pack the ROM as .zip. Optional: Python packages rarfile (for .rar) / py7zr (for .7z).'
)

# Prefer these extensions when the library platform is known.
PLATFORM_ROM_EXTENSIONS: dict[str, frozenset[str]] = {
    'NES': frozenset({'.nes', '.fds', '.unf', '.unif'}),
    'SNES': frozenset({'.smc', '.sfc'}),
    'N64': frozenset({'.n64', '.z64', '.v64'}),
    'GB': frozenset({'.gb'}),
    'GBC': frozenset({'.gbc', '.gb'}),
    'GBA': frozenset({'.gba'}),
    'NDS': frozenset({'.nds'}),
    'N3DS': frozenset({'.3ds', '.cia'}),
    'VB': frozenset({'.vb', '.vboy'}),
    'NGC': frozenset({'.iso', '.gcm', '.rvz', '.ciso', '.dol'}),
    'WII': frozenset({'.iso', '.wbfs', '.rvz', '.wad', '.dol'}),
    'PSX': frozenset({'.cue', '.chd', '.iso', '.bin', '.pbp', '.img'}),
    'PSP': frozenset({'.iso', '.cso', '.pbp', '.chd'}),
    'PCE': frozenset({'.pce', '.cue', '.chd'}),
    'SEGA_MD': frozenset({'.md', '.smd', '.gen', '.bin'}),
    'SEGA_MS': frozenset({'.sms'}),
    'SEGA_GG': frozenset({'.gg'}),
    'SEGA_32X': frozenset({'.32x'}),
    'SEGA_CD': frozenset({'.cue', '.chd', '.iso', '.bin'}),
    'SEGA_SATURN': frozenset({'.cue', '.chd', '.iso', '.bin'}),
    'SEGA_DC': frozenset({'.gdi', '.cdi', '.chd', '.cue', '.iso'}),
    'ATARI_2600': frozenset({'.a26', '.bin', '.rom'}),
    'ATARI_5200': frozenset({'.a52', '.bin'}),
    'ATARI_7800': frozenset({'.a78', '.bin'}),
    'LYNX': frozenset({'.lnx'}),
    'JAGUAR': frozenset({'.jag', '.j64', '.rom'}),
    'WS': frozenset({'.ws', '.wsc'}),
    'NGP': frozenset({'.ngp', '.ngc'}),
    'COLECO': frozenset({'.col', '.rom', '.bin'}),
    'VECTREX': frozenset({'.vec', '.bin'}),
    'NEOGEO': frozenset({'.zip', '.7z'}),
    'NEOGEO_CD': frozenset({'.cue', '.chd', '.iso'}),
    'ARCADE': frozenset({'.zip', '.7z'}),
    'SWITCH': frozenset({'.nsp', '.xci', '.nsz', '.xcz'}),
    'THREEDO': frozenset({'.cue', '.chd', '.iso'}),
    'SEGA_SG1000': frozenset({'.sg', '.sms'}),
    'SUPERGRAFX': frozenset({'.sgx', '.pce'}),
    'PCE_CD': frozenset({'.cue', '.chd', '.iso'}),
    'NGPC': frozenset({'.ngc', '.ngp'}),
    'SUPERVISION': frozenset({'.sv'}),
    'GX4000': frozenset({'.cpr'}),
    'ASTROCADE': frozenset({'.bin'}),
    'ARCADIA': frozenset({'.bin'}),
    'INTV': frozenset({'.int', '.rom'}),
    'CHAF': frozenset({'.chf', '.bin'}),
    'O2EM': frozenset({'.bin'}),
    'POKE_MINI': frozenset({'.min'}),
    'GAME_WATCH': frozenset({'.mgw'}),
    'CD_I': frozenset({'.chd', '.cue', '.iso'}),
    'SEGA_PICO': frozenset({'.md', '.bin', '.sms'}),
    'JAGUAR_CD': frozenset({'.cdi', '.cue', '.iso', '.chd'}),
    'WII_U': frozenset({'.wud', '.wux', '.wua'}),
    'AMIGA': frozenset({'.adf', '.ipf', '.hdf', '.adz'}),
    'AMIGA_CD32': frozenset({'.cue', '.chd', '.iso', '.adf'}),
    'MSX': frozenset({'.rom', '.mx1', '.mx2', '.dsk', '.cas'}),
    'ZX_SPECTRUM': frozenset({'.tzx', '.tap', '.z80', '.sna', '.dsk'}),
    'CPC': frozenset({'.dsk', '.cdt', '.cpr'}),
    'ATARI_ST': frozenset({'.st', '.stx', '.msa', '.ipf'}),
    'APPLE_II': frozenset({'.dsk', '.do', '.po', '.2mg', '.nib'}),
    'ATARI_8BIT': frozenset({'.atr', '.xex', '.xfd', '.atx', '.rom', '.car', '.bin'}),
    'X68000': frozenset({'.dim', '.xdf', '.hdm'}),
    'PC_98': frozenset({'.fdi', '.hdi', '.nhd', '.d88'}),
    'BBC_MICRO': frozenset({'.ssd', '.dsd', '.uef', '.bbc', '.img'}),
    'VICE_X64SC': frozenset({'.d64', '.prg', '.tap', '.crt', '.g64'}),
    'VICE_X128': frozenset({'.d64', '.d71', '.prg'}),
    'VICE_XVIC': frozenset({'.prg', '.tap', '.crt'}),
    'VICE_XPLUS4': frozenset({'.prg', '.tap', '.d64'}),
    'VICE_XPET': frozenset({'.prg', '.tap'}),
}

# Every suffix we advertise per platform — scan, peel, hash, and play
# resolution must accept this set (plus archives). Union into ROM_EXTENSIONS
# so a new leaf cannot land in PLATFORM_ROM_EXTENSIONS and stay invisible.
PLATFORM_DUMP_SUFFIXES = frozenset().union(*PLATFORM_ROM_EXTENSIONS.values())
ROM_EXTENSIONS = ROM_EXTENSIONS | PLATFORM_DUMP_SUFFIXES

# When a .cue is chosen, also extract these sibling extensions from the same archive folder.
CUE_COMPANION_EXTENSIONS = frozenset({'.bin', '.img', '.iso', '.raw', '.wav'})

MAX_NEST_DEPTH = 3
MIN_ROM_BYTES_PREFERRED = 1024
DEFAULT_MAX_ROM_OUTPUT_BYTES = 64 * 1024**3


class ArchiveRomError(Exception):
    """Raised when an archive cannot be used for emulation."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 400,
        code: str = 'archive_error',
        hint: str | None = None,
    ):
        self.message = message
        self.status_code = status_code
        self.code = code
        self.hint = hint
        super().__init__(message)

    def to_dict(self) -> dict[str, str]:
        payload = {'error': self.message, 'code': self.code}
        if self.hint:
            payload['hint'] = self.hint
        return payload


class RomExpansionBudget:
    """Mutable byte budget shared by every output produced for one request."""

    def __init__(self, limit: int = DEFAULT_MAX_ROM_OUTPUT_BYTES):
        self.limit = max(0, int(limit))
        self.remaining = self.limit

    def consume(self, size: int) -> None:
        size = max(0, int(size))
        if size > self.remaining:
            raise ArchiveRomError(
                'Expanded archive output exceeds the 64 GiB limit',
                status_code=413,
                code='archive_too_large',
            )
        self.remaining -= size

    def copy_stream(self, src, dest, chunk_size: int = 1024 * 1024) -> int:
        total = 0
        while True:
            chunk = src.read(min(chunk_size, self.remaining + 1))
            if not chunk:
                return total
            self.consume(len(chunk))
            dest.write(chunk)
            total += len(chunk)
