"""Unit tests for ROM archive extract-on-play (zip / 7z / gz)."""

from __future__ import annotations

import gzip
import os
import zipfile
from pathlib import Path

import pytest

from oneirodex.utils.rom_archive import (
    ArchiveRomError,
    bundle_playable_rom_zip,
    choose_rom_member,
    extract_rom_from_rar,
    extract_rom_from_7z,
    extract_rom_from_zip,
    find_archive_extractors,
    path_supports_browser_extract,
    resolve_playable_rom_path,
)
from oneirodex.utils.rom_archive_types import RomExpansionBudget
from oneirodex.utils.rom_archive_zip import extract_rom_from_gz


def test_choose_prefers_platform_extension():
    members = [
        ('readme.txt', 10),  # not a rom — caller filters first
        ('junk.bin', 50),
        ('Game.nes', 40_000),
        ('Game.smc', 500_000),
    ]
    # Only pass ROM-like names (as list_roms would).
    roms = [(n, s) for n, s in members if Path(n).suffix.lower() in {'.bin', '.nes', '.smc'}]
    assert choose_rom_member(roms, platform='NES') == 'Game.nes'
    assert choose_rom_member(roms, platform='SNES') == 'Game.smc'


def test_choose_prefers_larger_over_tiny_junk():
    members = [
        ('tiny.nes', 128),
        ('real.nes', 131_072),
    ]
    assert choose_rom_member(members, platform='NES') == 'real.nes'


def test_choose_prefers_cue_over_bin():
    members = [
        ('disc.bin', 700_000_000),
        ('disc.cue', 200),
    ]
    assert choose_rom_member(members, platform='PSX') == 'disc.cue'


def test_resolve_zip_nested_folder(tmp_path):
    zip_path = tmp_path / 'game.zip'
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.writestr('nested/Adventure.nes', b'NESROMDATA')
    cache = tmp_path / 'cache'
    path, name = resolve_playable_rom_path(str(zip_path), cache_dir=str(cache))
    assert name == 'Adventure.nes'
    assert Path(path).read_bytes() == b'NESROMDATA'


def test_resolve_zip_platform_pick(tmp_path):
    zip_path = tmp_path / 'multi.zip'
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.writestr('a.smc', b'S' * 10_000)
        zf.writestr('b.nes', b'N' * 8_000)
    cache = tmp_path / 'cache'
    path, name = resolve_playable_rom_path(
        str(zip_path),
        cache_dir=str(cache),
        platform='NES',
    )
    assert name == 'b.nes'
    assert Path(path).read_bytes() == b'N' * 8_000


def test_resolve_nested_zip_member(tmp_path):
    inner = tmp_path / 'inner.zip'
    with zipfile.ZipFile(inner, 'w') as zf:
        zf.writestr('deep/Hero.gba', b'GBAROM')
    outer = tmp_path / 'outer.zip'
    with zipfile.ZipFile(outer, 'w') as zf:
        zf.write(inner, arcname='pack/inner.zip')
    cache = tmp_path / 'cache'
    path, name = resolve_playable_rom_path(str(outer), cache_dir=str(cache), platform='GBA')
    assert name == 'Hero.gba'
    assert Path(path).read_bytes() == b'GBAROM'


def test_resolve_cue_bin_companions(tmp_path):
    zip_path = tmp_path / 'psx.zip'
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.writestr('game/disc.cue', b'FILE "disc.bin" BINARY\n')
        zf.writestr('game/disc.bin', b'BINDATA' * 100)
        zf.writestr('game/readme.txt', b'ignore')
    cache = tmp_path / 'cache'
    path, name = resolve_playable_rom_path(str(zip_path), cache_dir=str(cache), platform='PSX')
    assert name == 'disc.cue'
    assert Path(path).is_file()
    assert (cache / 'disc.bin').is_file()
    assert (cache / 'disc.bin').read_bytes() == b'BINDATA' * 100


def test_resolve_gz_rom(tmp_path):
    gz_path = tmp_path / 'Adventure.nes.gz'
    with gzip.open(gz_path, 'wb') as fh:
        fh.write(b'NESGZDATA')
    cache = tmp_path / 'cache'
    path, name = resolve_playable_rom_path(str(gz_path), cache_dir=str(cache))
    assert name == 'Adventure.nes'
    assert Path(path).read_bytes() == b'NESGZDATA'


def test_zip_expansion_budget_exact_limit_and_overflow_cleanup(tmp_path):
    zip_path = tmp_path / 'budget.zip'
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.writestr('game.nes', b'12345')
    exact = tmp_path / 'exact'
    result = extract_rom_from_zip(str(zip_path), str(exact), budget=RomExpansionBudget(5))
    assert Path(result).read_bytes() == b'12345'

    over = tmp_path / 'over'
    with pytest.raises(ArchiveRomError) as exc:
        extract_rom_from_zip(str(zip_path), str(over), budget=RomExpansionBudget(4))
    assert (exc.value.status_code, exc.value.code) == (413, 'archive_too_large')
    assert not (over / 'game.nes').exists()


def test_zip_budget_aggregates_cue_companions(tmp_path):
    zip_path = tmp_path / 'cue.zip'
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.writestr('disc.cue', b'CUE')
        zf.writestr('disc.bin', b'IMAGE')
    cache = tmp_path / 'cache'
    with pytest.raises(ArchiveRomError) as exc:
        extract_rom_from_zip(str(zip_path), str(cache), platform='PSX', budget=RomExpansionBudget(7))
    assert exc.value.code == 'archive_too_large'
    assert not (cache / 'disc.bin').exists()
    assert not (cache / 'disc.cue').exists()


def test_nested_zip_budget_is_shared(tmp_path):
    inner = tmp_path / 'inner.zip'
    with zipfile.ZipFile(inner, 'w') as zf:
        zf.writestr('game.gba', b'12345')
    outer = tmp_path / 'outer.zip'
    with zipfile.ZipFile(outer, 'w') as zf:
        zf.write(inner, 'inner.zip')
    cache = tmp_path / 'cache'
    with pytest.raises(ArchiveRomError) as exc:
        extract_rom_from_zip(str(outer), str(cache), platform='GBA', budget=RomExpansionBudget(inner.stat().st_size + 4))
    assert exc.value.code == 'archive_too_large'
    assert not (cache / 'game.gba').exists()


def test_gzip_budget_exact_limit_and_overflow_cleanup(tmp_path):
    gz_path = tmp_path / 'game.nes.gz'
    with gzip.open(gz_path, 'wb') as fh:
        fh.write(b'12345')
    exact = extract_rom_from_gz(str(gz_path), str(tmp_path / 'exact'), budget=RomExpansionBudget(5))
    assert Path(exact).read_bytes() == b'12345'
    over = tmp_path / 'over'
    with pytest.raises(ArchiveRomError) as exc:
        extract_rom_from_gz(str(gz_path), str(over), budget=RomExpansionBudget(4))
    assert exc.value.code == 'archive_too_large'
    assert not (over / 'game.nes').exists()


def test_cli_archive_streaming_uses_budget_and_kills_overflow(tmp_path, monkeypatch):
    from io import BytesIO
    from oneirodex.utils import rom_archive

    processes = []

    class FakeProcess:
        def __init__(self, output):
            self.stdout = BytesIO(output)
            self.returncode = 0
            self.killed = False

        def wait(self):
            return self.returncode

        def kill(self):
            self.killed = True
            self.returncode = -9

    def fake_popen(command, **kwargs):
        process = FakeProcess(b'12345')
        processes.append(process)
        return process

    monkeypatch.setattr(rom_archive.subprocess, 'Popen', fake_popen)
    exact = tmp_path / 'exact' / 'game.nes'
    rom_archive._extract_cli_member(['7z', 'x', '-so'], str(exact), RomExpansionBudget(5))
    assert exact.read_bytes() == b'12345'
    assert not processes[-1].killed

    over = tmp_path / 'over' / 'game.nes'
    with pytest.raises(ArchiveRomError) as exc:
        rom_archive._extract_cli_member(['7z', 'x', '-so'], str(over), RomExpansionBudget(4))
    assert (exc.value.status_code, exc.value.code) == (413, 'archive_too_large')
    assert processes[-1].killed
    assert not over.exists()


def test_py7zr_declared_expansion_limit_is_reported_and_cleaned(tmp_path):
    py7zr = pytest.importorskip('py7zr')
    archive_path = tmp_path / 'large.7z'
    with py7zr.SevenZipFile(archive_path, mode='w') as archive:
        archive.writestr(b'X' * 128, 'game.nes')

    cache = tmp_path / 'cache'
    with pytest.raises(ArchiveRomError) as exc:
        extract_rom_from_7z(str(archive_path), str(cache), budget=RomExpansionBudget(32))

    assert (exc.value.status_code, exc.value.code) == (413, 'archive_too_large')
    assert not (cache / 'game.nes').exists()


def test_rar_stream_overflow_is_reported_and_cleaned(tmp_path, monkeypatch):
    import io
    import sys
    import types

    rar_path = tmp_path / 'large.rar'
    rar_path.write_bytes(b'fake rar')

    class Info:
        filename = 'game.nes'
        file_size = 128

        @staticmethod
        def is_dir():
            return False

    class FakeRarFile:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def infolist():
            return [Info()]

        @staticmethod
        def open(_name):
            return io.BytesIO(b'X' * 128)

    fake_rarfile = types.ModuleType('rarfile')
    fake_rarfile.RarFile = FakeRarFile
    monkeypatch.setitem(sys.modules, 'rarfile', fake_rarfile)
    monkeypatch.setattr('oneirodex.utils.rom_archive._configure_rarfile_tools', lambda _module: ['fake'])
    monkeypatch.setattr('oneirodex.utils.rom_archive.find_archive_extractors', lambda: {})
    cache = tmp_path / 'cache'

    with pytest.raises(ArchiveRomError) as exc:
        extract_rom_from_rar(str(rar_path), str(cache), budget=RomExpansionBudget(32))

    assert (exc.value.status_code, exc.value.code) == (413, 'archive_too_large')
    assert not (cache / 'game.nes').exists()


def test_resolve_tar_gz_rejected(tmp_path):
    bad = tmp_path / 'archive.tar.gz'
    with gzip.open(bad, 'wb') as fh:
        fh.write(b'not-a-rom')
    with pytest.raises(ArchiveRomError) as exc:
        resolve_playable_rom_path(str(bad), cache_dir=str(tmp_path / 'c'))
    assert exc.value.status_code == 415
    assert exc.value.code == 'unsupported_format'


def test_path_supports_browser_extract_gz():
    assert path_supports_browser_extract('/lib/Adventure.nes.gz') is True
    assert path_supports_browser_extract('/lib/archive.tar.gz') is False
    assert path_supports_browser_extract('/lib/game.zip') is True
    assert path_supports_browser_extract('/lib/game.tar') is False


def test_empty_zip_clear_error(tmp_path):
    zip_path = tmp_path / 'empty.zip'
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.writestr('readme.txt', b'no rom here')
    with pytest.raises(ArchiveRomError) as exc:
        extract_rom_from_zip(str(zip_path), str(tmp_path / 'c'))
    assert exc.value.code == 'no_playable_member'
    assert exc.value.to_dict()['error']


def test_resolve_7z_with_py7zr(tmp_path):
    py7zr = pytest.importorskip('py7zr')
    seven = tmp_path / 'game.7z'
    with py7zr.SevenZipFile(seven, 'w') as archive:
        archive.writestr(b'SNESDATA', 'Folder/Quest.sfc')
    cache = tmp_path / 'cache'
    path, name = resolve_playable_rom_path(str(seven), cache_dir=str(cache), platform='SNES')
    assert name == 'Quest.sfc'
    assert Path(path).read_bytes() == b'SNESDATA'


def test_archive_error_payload_shape():
    err = ArchiveRomError('boom', status_code=415, code='missing_dependency', hint='install x')
    assert err.to_dict() == {
        'error': 'boom',
        'code': 'missing_dependency',
        'hint': 'install x',
    }


def test_bundle_cue_bin_zips_and_rewrites_paths(tmp_path):
    disc_dir = tmp_path / 'disc'
    disc_dir.mkdir()
    cue_path = disc_dir / 'Game (Disc 1).cue'
    cue_path.write_text(
        'FILE "subfolder/Game (Disc 1).bin" BINARY\n'
        '  TRACK 01 MODE2/2352\n'
        '    INDEX 01 00:00:00\n',
        encoding='utf-8',
    )
    (disc_dir / 'Game (Disc 1).bin').write_bytes(b'BINDATA' * 1000)
    (disc_dir / 'readme.txt').write_text('ignore me', encoding='utf-8')

    cache = tmp_path / 'cache'
    zip_path, filename = bundle_playable_rom_zip(str(cue_path), str(cache))

    assert filename == 'play.zip'
    assert Path(zip_path) == cache / 'play.zip'

    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        assert names == {'Game (Disc 1).cue', 'Game (Disc 1).bin'}
        info = zf.getinfo('Game (Disc 1).cue')
        assert info.compress_type == zipfile.ZIP_STORED
        cue_contents = zf.read('Game (Disc 1).cue').decode('utf-8')
        assert 'FILE "Game (Disc 1).bin" BINARY' in cue_contents
        assert 'subfolder' not in cue_contents
        assert zf.read('Game (Disc 1).bin') == b'BINDATA' * 1000


def test_bundle_reuses_fresh_zip(tmp_path):
    disc_dir = tmp_path / 'disc'
    disc_dir.mkdir()
    cue_path = disc_dir / 'disc.cue'
    cue_path.write_text('FILE "disc.bin" BINARY\n', encoding='utf-8')
    (disc_dir / 'disc.bin').write_bytes(b'X' * 100)

    cache = tmp_path / 'cache'
    zip_path_1, _ = bundle_playable_rom_zip(str(cue_path), str(cache))
    first_mtime = os.path.getmtime(zip_path_1)

    zip_path_2, _ = bundle_playable_rom_zip(str(cue_path), str(cache))
    assert zip_path_2 == zip_path_1
    assert os.path.getmtime(zip_path_2) == first_mtime


def test_bundle_single_iso_unchanged(tmp_path):
    disc_dir = tmp_path / 'disc'
    disc_dir.mkdir()
    iso_path = disc_dir / 'game.iso'
    iso_path.write_bytes(b'ISODATA')

    cache = tmp_path / 'cache'
    result_path, filename = bundle_playable_rom_zip(str(iso_path), str(cache))

    assert result_path == str(iso_path)
    assert filename == 'game.iso'
    assert not (cache / 'play.zip').exists()


def test_bundle_cue_without_companions_unchanged(tmp_path):
    disc_dir = tmp_path / 'disc'
    disc_dir.mkdir()
    cue_path = disc_dir / 'lone.cue'
    cue_path.write_text('FILE "lone.bin" BINARY\n', encoding='utf-8')

    cache = tmp_path / 'cache'
    result_path, filename = bundle_playable_rom_zip(str(cue_path), str(cache))

    assert result_path == str(cue_path)
    assert filename == 'lone.cue'
    assert not (cache / 'play.zip').exists()


def test_rar_missing_extractor_returns_hint(tmp_path, monkeypatch):
    rar_path = tmp_path / 'game.rar'
    rar_path.write_bytes(b'Rar!\x00fake')

    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == 'rarfile':
            raise ImportError('no rarfile')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', fake_import)
    monkeypatch.setattr(
        'oneirodex.utils.rom_archive.find_archive_extractors',
        lambda: {},
    )
    with pytest.raises(ArchiveRomError) as exc:
        resolve_playable_rom_path(str(rar_path), cache_dir=str(tmp_path / 'c'))
    payload = exc.value.to_dict()
    assert exc.value.status_code == 415
    assert payload['code'] == 'missing_extractor'
    assert 'error' in payload
    assert 'hint' in payload
    hint = payload['hint'].lower()
    assert '7z' in hint or 'bsdtar' in hint or 'p7zip' in hint
    assert 'zip' in hint


def test_rar_extract_via_stubbed_7z(tmp_path, monkeypatch):
    """When 7z is on PATH (stubbed), extract succeeds without rarfile."""
    rar_path = tmp_path / 'pack.rar'
    rar_path.write_bytes(b'fake-rar')
    fake_7z = tmp_path / 'fake-7z'
    fake_7z.write_text('#!/bin/sh\n', encoding='utf-8')
    cache = tmp_path / 'cache'
    cache.mkdir()

    list_calls = {'n': 0}

    def fake_run(cmdline, **kwargs):
        from subprocess import CompletedProcess

        if 'l' in cmdline and '-slt' in cmdline:
            list_calls['n'] += 1
            stdout = (
                'Path = nested/Hero.nes\n'
                'Size = 9\n'
                'Attributes = A\n'
                '\n'
            )
            return CompletedProcess(cmdline, 0, stdout=stdout, stderr='')
        return CompletedProcess(cmdline, 1, stdout='', stderr=f'unexpected {cmdline}')

    def fake_extract(cmdline, destination, budget):
        Path(destination).write_bytes(b'NESROMDAT')
        budget.consume(9)

    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == 'rarfile':
            raise ImportError('no rarfile')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', fake_import)
    monkeypatch.setattr(
        'oneirodex.utils.rom_archive.find_archive_extractors',
        lambda: {'7z': str(fake_7z)},
    )
    monkeypatch.setattr('oneirodex.utils.rom_archive._run_extractor', fake_run)
    monkeypatch.setattr('oneirodex.utils.rom_archive._extract_cli_member', fake_extract)

    path, name = resolve_playable_rom_path(
        str(rar_path),
        cache_dir=str(cache),
        platform='NES',
    )
    assert name == 'Hero.nes'
    assert Path(path).read_bytes() == b'NESROMDAT'
    assert list_calls['n'] >= 1


def test_find_archive_extractors_shape(monkeypatch):
    monkeypatch.setattr(
        'oneirodex.utils.rom_archive.shutil.which',
        lambda name: f'/usr/bin/{name}' if name in ('7z', 'bsdtar') else None,
    )
    found = find_archive_extractors()
    assert found['7z'] == '/usr/bin/7z'
    assert found['bsdtar'] == '/usr/bin/bsdtar'
    assert 'unrar' not in found


def test_extract_rom_from_rar_missing_tool_direct(tmp_path, monkeypatch):
    rar_path = tmp_path / 'x.rar'
    rar_path.write_bytes(b'x')
    monkeypatch.setattr(
        'oneirodex.utils.rom_archive.find_archive_extractors',
        lambda: {},
    )
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == 'rarfile':
            raise ImportError('no')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', fake_import)
    with pytest.raises(ArchiveRomError) as exc:
        extract_rom_from_rar(str(rar_path), str(tmp_path / 'c'))
    assert exc.value.code == 'missing_extractor'


# --- RAR5 on the live box, 2026-09-22 ---------------------------------------
#
# He reported "games for NeoGeo CD does not play the rom and has the unrar tool
# error". Reproduced on the box: the 7-Zip in the image *lists* a RAR5 and then
# writes 28 zero-byte files ("Unsupported Method"), rarfile streaming through
# that same backend returns a short read, and bsdtar -- which decodes the
# archive perfectly -- was never reached because the code assumed the tool that
# listed could also extract. These three cover each link.

def _fake_tools(tmp_path):
    seven = tmp_path / 'fake-7z'
    seven.write_text('#!/bin/sh\n', encoding='utf-8')
    tar = tmp_path / 'fake-bsdtar'
    tar.write_text('#!/bin/sh\n', encoding='utf-8')
    return str(seven), str(tar)


def _no_rarfile(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == 'rarfile':
            raise ImportError('no rarfile')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', fake_import)


def test_a_listing_tool_that_cannot_decode_falls_back_to_the_other(tmp_path, monkeypatch):
    """7z lists the RAR5, writes an empty file, and bsdtar finishes the job."""
    from subprocess import CompletedProcess

    rar_path = tmp_path / 'Game [!][NGCD-058].rar'
    rar_path.write_bytes(b'fake-rar')
    cache = tmp_path / 'cache'
    cache.mkdir()
    seven, tar = _fake_tools(tmp_path)
    member = 'Game [!][NGCD-058]/Game [!][NGCD-058].cue'
    used = []

    def fake_run(cmdline, **kwargs):
        if '-slt' in cmdline:
            return CompletedProcess(cmdline, 0, stdout=f'Path = {member}\nSize = 12\nAttributes = A\n\n', stderr='')
        return CompletedProcess(cmdline, 0, stdout='', stderr='')

    def fake_extract(cmdline, destination, budget):
        if cmdline[0] == seven:
            used.append('7z')
            raise ArchiveRomError('Unsupported Method', code='extract_failed')
        used.append('bsdtar')
        assert any(r'\[!\]' in arg for arg in cmdline), cmdline
        Path(destination).write_bytes(b'FILE "x.bin"')
        budget.consume(Path(destination).stat().st_size)

    _no_rarfile(monkeypatch)
    monkeypatch.setattr('oneirodex.utils.rom_archive.find_archive_extractors', lambda: {'7z': seven, 'bsdtar': tar})
    monkeypatch.setattr('oneirodex.utils.rom_archive._run_extractor', fake_run)
    monkeypatch.setattr('oneirodex.utils.rom_archive._extract_cli_member', fake_extract)

    path, name = resolve_playable_rom_path(str(rar_path), cache_dir=str(cache), platform='NEOGEO_CD')
    assert name == 'Game [!][NGCD-058].cue'
    assert Path(path).read_bytes() == b'FILE "x.bin"'
    assert used == ['7z', 'bsdtar']  # tried the lister first, then the other tool


def test_an_empty_extract_is_never_served_as_a_rom(tmp_path, monkeypatch):
    """Both tools write zero bytes: fail honestly and leave no husk behind."""
    from subprocess import CompletedProcess

    from oneirodex.utils.rom_archive import ArchiveRomError

    rar_path = tmp_path / 'pack.rar'
    rar_path.write_bytes(b'fake-rar')
    cache = tmp_path / 'cache'
    cache.mkdir()
    seven, tar = _fake_tools(tmp_path)

    def fake_run(cmdline, **kwargs):
        if '-slt' in cmdline:
            return CompletedProcess(cmdline, 0, stdout='Path = Hero.nes\nSize = 9\nAttributes = A\n\n', stderr='')
        return CompletedProcess(cmdline, 0, stdout='', stderr='')

    def fake_extract(_cmdline, destination, _budget):
        Path(destination).write_bytes(b'')

    _no_rarfile(monkeypatch)
    monkeypatch.setattr('oneirodex.utils.rom_archive.find_archive_extractors', lambda: {'7z': seven, 'bsdtar': tar})
    monkeypatch.setattr('oneirodex.utils.rom_archive._run_extractor', fake_run)
    monkeypatch.setattr('oneirodex.utils.rom_archive._extract_cli_member', fake_extract)

    with pytest.raises(ArchiveRomError) as exc:
        resolve_playable_rom_path(str(rar_path), cache_dir=str(cache), platform='NES')
    assert exc.value.code == 'extract_failed'
    assert not (cache / 'Hero.nes').exists(), 'a zero-byte husk must not survive to be cached'


def test_a_short_rarfile_read_is_refused(tmp_path, monkeypatch):
    """rarfile streaming through a backend that cannot decode returns a short
    stream instead of raising; half a ROM must not reach the player."""
    import sys
    import types

    from oneirodex.utils.rom_archive import extract_rom_from_rar, ArchiveRomError

    rar_path = tmp_path / 'pack.rar'
    rar_path.write_bytes(b'fake-rar')
    cache = tmp_path / 'cache'
    cache.mkdir()

    class FakeInfo:
        filename = 'Hero.nes'
        file_size = 4096

        def is_dir(self):
            return False

    class FakeMember:
        def __init__(self):
            self._left = 1

        def read(self, _n=None):
            # 5 of the 4096 bytes the header promised, then end of stream.
            if not self._left:
                return b''
            self._left = 0
            return b'short'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class FakeRarFile:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def infolist(self):
            return [FakeInfo()]

        def open(self, _name):
            return FakeMember()

    fake = types.ModuleType('rarfile')
    fake.RarFile = FakeRarFile
    monkeypatch.setitem(sys.modules, 'rarfile', fake)
    monkeypatch.setattr('oneirodex.utils.rom_archive._configure_rarfile_tools', lambda mod: ['7z'])
    monkeypatch.setattr('oneirodex.utils.rom_archive.find_archive_extractors', lambda: {'7z': '/usr/bin/7z'})
    monkeypatch.setattr(
        'oneirodex.utils.rom_archive._extract_archive_via_cli',
        lambda *a, **k: (_ for _ in ()).throw(ArchiveRomError('cli also failed', code='extract_failed')),
    )

    with pytest.raises(ArchiveRomError) as exc:
        extract_rom_from_rar(str(rar_path), str(cache), platform='NES')
    assert exc.value.code == 'extract_failed'
    assert not (cache / 'Hero.nes').exists()


def test_one_damaged_track_does_not_cost_the_whole_cd_rip(tmp_path, monkeypatch):
    """A CRC error on track 12 of 34 must not hide the cue sitting at member 34.

    bsdtar stops the whole run on a damaged member, so the members listed after
    it never land -- which is exactly where the cue lives in a NeoGeo CD rip.
    The extractor drops the bad track and asks again for the rest.
    """
    from subprocess import CompletedProcess

    rar_path = tmp_path / 'Aero [!][SW2].rar'
    rar_path.write_bytes(b'fake-rar')
    cache = tmp_path / 'cache'
    cache.mkdir()
    seven, tar = _fake_tools(tmp_path)
    folder = 'Aero [!][SW2]'
    cue = f'{folder}/Aero [!][SW2].cue'
    good = f'{folder}/Aero (Track 11 of 34)[!][SW2].wav'
    bad = f'{folder}/Aero (Track 12 of 34)[!][SW2].wav'
    passes = []

    def fake_run(cmdline, **kwargs):
        if '-tf' in cmdline:
            names = chr(10).join((good, bad, cue))
            return CompletedProcess(cmdline, 0, stdout=names, stderr='')
        return CompletedProcess(cmdline, 0, stdout='', stderr='')

    def fake_extract(cmdline, destination, budget):
        member_name = next(arg for arg in cmdline if arg.endswith('.cue') or arg.endswith('.wav'))
        member_name = member_name.replace(chr(92), '')
        passes.append([member_name])
        if 'Track 12' in member_name:
            raise ArchiveRomError('File CRC error', code='extract_failed')
        Path(destination).write_bytes(b'REAL BYTES')
        budget.consume(11)

    _no_rarfile(monkeypatch)
    monkeypatch.setattr('oneirodex.utils.rom_archive.find_archive_extractors', lambda: {'bsdtar': tar})
    monkeypatch.setattr('oneirodex.utils.rom_archive._run_extractor', fake_run)
    monkeypatch.setattr('oneirodex.utils.rom_archive._extract_cli_member', fake_extract)

    path, name = resolve_playable_rom_path(str(rar_path), cache_dir=str(cache), platform='NEOGEO_CD')
    assert name == 'Aero [!][SW2].cue'
    assert Path(path).read_bytes() == b'REAL BYTES'
    assert len(passes) == 3, 'extract each selected member separately within the shared budget'
    assert any('Track 12' in member for [member] in passes)
    assert not (cache / folder / Path(bad).name).exists()

