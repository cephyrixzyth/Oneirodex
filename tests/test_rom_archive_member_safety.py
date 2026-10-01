"""Archive member names are attacker-controlled (finding: ``..`` escapes the ROM cache).

A zip or tar disguised as ``.7z`` / ``.rar`` reaches the host ``7z`` / ``bsdtar``
fallback, whose listing used to hand member names on verbatim. The extract and
flatten steps then joined them onto the cache directory, so ``../victim.nes``
named a file *outside* the cache that ``os.replace`` moved into place and the
route then served (or a cleanup deleted). These tests craft such archives.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

from oneirodex.utils import rom_archive
from oneirodex.utils.rom_archive import (
    ArchiveRomError,
    _extract_archive_via_cli,
    _list_roms_via_7z,
    _list_roms_via_bsdtar,
    _replace_in_cache,
    _unlink_in_cache,
    extract_rom_from_7z,
    resolve_playable_rom_path,
)
from oneirodex.utils.rom_archive_select import _safe_member_name

SEVEN_Z = shutil.which('7z') or shutil.which('7za')
BSDTAR = shutil.which('bsdtar')
needs_7z = pytest.mark.skipif(not SEVEN_Z, reason='host 7z not installed')
needs_bsdtar = pytest.mark.skipif(not BSDTAR, reason='host bsdtar not installed')

VICTIM = b'VICTIM-BYTES' * 10
GOOD = b'GOOD-ROM-BYTES' * 50


def _zip(path: Path, members: list[tuple[str, bytes]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, 'w') as archive:
        for name, data in members:
            archive.writestr(name, data)  # writestr keeps '../' and '/' as given
    return path


def _tar(path: Path, members: list[tuple[str, bytes]], links: list[tuple[str, str]] = ()) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, 'w') as archive:
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        for name, target in links:
            info = tarfile.TarInfo(name)
            info.type = tarfile.SYMTYPE
            info.linkname = target
            archive.addfile(info)
    return path


def _cache(tmp_path: Path) -> tuple[Path, Path]:
    """``(cache_dir, victim)``: the victim sits where ``../victim.nes`` points."""
    cache_dir = tmp_path / 'rom_cache' / 'game'
    cache_dir.mkdir(parents=True)
    victim = cache_dir.parent / 'victim.nes'
    victim.write_bytes(VICTIM)
    return cache_dir, victim


# --------------------------------------------------------------------------
# the name filter
# --------------------------------------------------------------------------

@pytest.mark.parametrize('name, expected', [
    ('game.nes', 'game.nes'),
    ('a/b/game.nes', 'a/b/game.nes'),
    ('a\\b\\game.nes', 'a/b/game.nes'),
    ('./game.nes', './game.nes'),
    ('Game Vol. 1./x.nes', 'Game Vol. 1./x.nes'),
    ('a..b/game.nes', 'a..b/game.nes'),
])
def test_safe_member_name_keeps_ordinary_names(name, expected):
    assert _safe_member_name(name) == expected


@pytest.mark.parametrize('name', [
    '', None,
    '../victim.nes',
    'a/../../victim.nes',
    'a/..',
    '..\\victim.nes',
    'a\\..\\..\\victim.nes',
    '/abs/victim.nes',
    '\\abs\\victim.nes',
    '//server/share/x.nes',
    '\\\\server\\share\\x.nes',
    'C:/Windows/x.nes',
    'c:\\x.nes',
    'a/.. /victim.nes',      # Windows folds the padded forms back into '..'
    'a/.../victim.nes',
    'x\x00.nes',
])
def test_safe_member_name_refuses_anything_that_can_leave_the_directory(name):
    assert _safe_member_name(name) is None


# --------------------------------------------------------------------------
# listings drop hostile members (no host tool needed: output is simulated)
# --------------------------------------------------------------------------

def _7z_block(path, size=100, attrs='A', link=''):
    return (
        f'Path = {path}\nFolder = -\nSize = {size}\nAttributes = {attrs}\n'
        f'Symbolic Link = {link}\n'
    )


def _fake_run(stdout):
    return lambda cmdline, **kw: subprocess.CompletedProcess(cmdline, 0, stdout=stdout, stderr='')


def test_7z_listing_drops_traversal_absolute_and_link_members(monkeypatch):
    stdout = '\n'.join([
        _7z_block('../victim.nes'),
        _7z_block('/etc/abs.nes'),
        _7z_block('C:\\x\\drive.nes'),
        _7z_block('a/../../b.nes'),
        _7z_block('link.nes', size=13, link='/etc/hostname'),
        _7z_block('sub\\good.nes', size=4096),
        _7z_block('plain.nes', size=2048),
    ])
    monkeypatch.setattr(rom_archive, '_run_extractor', _fake_run(stdout))
    assert _list_roms_via_7z('x.7z', '/usr/bin/7z') == [('sub/good.nes', 4096), ('plain.nes', 2048)]


def test_bsdtar_listing_drops_traversal_and_absolute_members(monkeypatch):
    stdout = '../victim.nes\n/etc/abs.nes\nC:\\drive.nes\nok/game.nes\nsub/../../x.nes\nplain.nes\n'
    monkeypatch.setattr(rom_archive, '_run_extractor', _fake_run(stdout))
    assert _list_roms_via_bsdtar('x.tar', '/usr/bin/bsdtar') == [('ok/game.nes', 0), ('plain.nes', 0)]


def test_extract_paths_never_leave_the_cache(tmp_path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    paths = rom_archive._extract_paths_for(str(cache), ['../victim.nes', '/etc/x.nes', 'ok/game.nes'])
    assert paths, 'the honest member still gets candidates'
    real = Path(os.path.realpath(cache))
    assert all(Path(os.path.realpath(p)).is_relative_to(real) for p in paths)
    assert not any(Path(p).name == 'victim.nes' or Path(p).name == 'x.nes' for p in paths)


# --------------------------------------------------------------------------
# containment helpers
# --------------------------------------------------------------------------

def _symlink_or_skip(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        os.symlink(target, link, target_is_directory=directory)
    except (OSError, NotImplementedError):
        pytest.skip('symlinks are not available here')


def test_replace_in_cache_refuses_a_source_outside_the_cache(tmp_path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    outside = tmp_path / 'outside.nes'
    outside.write_bytes(VICTIM)
    assert _replace_in_cache(str(cache), str(outside), str(cache / 'outside.nes')) is False
    assert outside.read_bytes() == VICTIM
    assert not (cache / 'outside.nes').exists()


def test_replace_in_cache_refuses_a_destination_outside_the_cache(tmp_path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    inside = cache / 'a.nes'
    inside.write_bytes(GOOD)
    assert _replace_in_cache(str(cache), str(inside), str(tmp_path / 'elsewhere.nes')) is False
    assert inside.read_bytes() == GOOD
    assert not (tmp_path / 'elsewhere.nes').exists()


def test_replace_in_cache_moves_a_plain_file_inside(tmp_path):
    cache = tmp_path / 'cache'
    (cache / 'sub').mkdir(parents=True)
    (cache / 'sub' / 'g.nes').write_bytes(GOOD)
    assert _replace_in_cache(str(cache), str(cache / 'sub' / 'g.nes'), str(cache / 'g.nes')) is True
    assert (cache / 'g.nes').read_bytes() == GOOD


def test_replace_in_cache_will_not_move_a_symlink(tmp_path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    secret = tmp_path / 'secret.nes'
    secret.write_bytes(VICTIM)
    _symlink_or_skip(cache / 'link.nes', secret)
    assert _replace_in_cache(str(cache), str(cache / 'link.nes'), str(cache / 'moved.nes')) is False
    assert secret.read_bytes() == VICTIM


def test_cleanup_does_not_delete_through_a_planted_directory_link(tmp_path):
    cache = tmp_path / 'cache'
    cache.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'x.nes').write_bytes(VICTIM)
    _symlink_or_skip(cache / 'dirlink', outside, directory=True)
    _unlink_in_cache(str(cache), str(cache / 'dirlink' / 'x.nes'))
    assert (outside / 'x.nes').read_bytes() == VICTIM


# --------------------------------------------------------------------------
# end to end with the real host tools
# --------------------------------------------------------------------------

@needs_7z
def test_zip_disguised_as_7z_cannot_relocate_a_victim_file(tmp_path):
    cache_dir, victim = _cache(tmp_path)
    archive = _zip(tmp_path / 'lib' / 'game.7z', [('../victim.nes', b'EVIL' * 100)])
    with pytest.raises(ArchiveRomError) as exc:
        extract_rom_from_7z(str(archive), str(cache_dir))
    assert exc.value.code == 'no_playable_member'
    assert victim.read_bytes() == VICTIM, 'the file the member name pointed at was not touched'
    assert list(cache_dir.iterdir()) == []


@needs_7z
def test_zip_disguised_as_7z_still_serves_the_honest_member(tmp_path):
    cache_dir, victim = _cache(tmp_path)
    archive = _zip(tmp_path / 'lib' / 'game.7z', [
        ('../victim.nes', b'EVIL' * 100),
        ('/abs.nes', b'ABS' * 100),
        ('ok/game.nes', GOOD),
    ])
    rom, name = resolve_playable_rom_path(str(archive), cache_dir=str(cache_dir))
    assert name == 'game.nes'
    assert Path(rom).read_bytes() == GOOD
    assert Path(rom).parent == cache_dir
    assert victim.read_bytes() == VICTIM


@needs_bsdtar
def test_tar_disguised_as_7z_cannot_relocate_a_victim_file_via_bsdtar(tmp_path, monkeypatch):
    cache_dir, victim = _cache(tmp_path)
    archive = _tar(tmp_path / 'lib' / 'game.7z', [('../victim.nes', b'EVIL' * 100), ('ok/game.nes', GOOD)])
    monkeypatch.setattr(rom_archive, 'find_archive_extractors', lambda: {'bsdtar': BSDTAR})
    dest = _extract_archive_via_cli(str(archive), str(cache_dir), archive_kind='7z')
    assert Path(dest) == cache_dir / 'game.nes'
    assert Path(dest).read_bytes() == GOOD
    assert victim.read_bytes() == VICTIM
    assert sorted(p.name for p in cache_dir.iterdir()) == ['game.nes']


@needs_bsdtar
def test_symlink_member_is_not_served_or_kept(tmp_path, monkeypatch):
    cache_dir, _victim = _cache(tmp_path)
    secret = tmp_path / 'secret.nes'
    secret.write_bytes(b'TOP-SECRET' * 20)
    archive = _tar(tmp_path / 'lib' / 'game.rar', [], links=[('game.nes', str(secret))])
    monkeypatch.setattr(rom_archive, 'find_archive_extractors', lambda: {'bsdtar': BSDTAR})
    with pytest.raises(ArchiveRomError):
        _extract_archive_via_cli(str(archive), str(cache_dir), archive_kind='rar')
    assert secret.read_bytes() == b'TOP-SECRET' * 20
    assert not os.path.lexists(cache_dir / 'game.nes'), 'the planted link is removed, not left for a later cache hit'


@needs_7z
def test_a_link_already_in_the_cache_is_not_a_cache_hit(tmp_path):
    """A stale/planted link at the destination is replaced, never returned."""
    cache_dir, _victim = _cache(tmp_path)
    secret = tmp_path / 'secret.nes'
    secret.write_bytes(b'TOP-SECRET' * 20)
    _symlink_or_skip(cache_dir / 'game.nes', secret)
    archive = _zip(tmp_path / 'lib' / 'game.7z', [('game.nes', GOOD)])
    dest = Path(_extract_archive_via_cli(str(archive), str(cache_dir), archive_kind='7z'))
    assert dest == cache_dir / 'game.nes'
    assert not dest.is_symlink()
    assert dest.read_bytes() == GOOD
    assert secret.read_bytes() == b'TOP-SECRET' * 20, 'extraction did not write through the link'


@needs_7z
def test_py7zr_archive_with_traversal_member_is_filtered(tmp_path):
    py7zr = pytest.importorskip('py7zr')
    cache_dir, victim = _cache(tmp_path)
    archive = tmp_path / 'lib' / 'game.7z'
    archive.parent.mkdir()
    try:
        with py7zr.SevenZipFile(archive, 'w') as writer:
            writer.writestr(b'EVIL' * 100, '../victim.nes')
    except Exception:  # noqa: BLE001 - some py7zr builds refuse to write such a name
        pytest.skip('py7zr refuses to craft a traversal member')
    with pytest.raises(ArchiveRomError):
        extract_rom_from_7z(str(archive), str(cache_dir))
    assert victim.read_bytes() == VICTIM
