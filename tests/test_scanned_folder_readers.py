"""Readers and writers that touch files inside a scanned (share-writable) folder.

The folder-download, NFO and firmware-import paths are covered in
test_folder_symlink_safety.py. These are the rest: the freshness check's
version file, the ``scripts/import_bios.py`` command line, and the sidecar
metadata read and write (with the write-permission probe next to it). Each one
used to follow a link planted (or swapped in after a check) by someone with
write access to the share. The move command's FIFO case is in
test_standalone_move.py.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

SECRET = b'TOP-SECRET-CONTENTS-' * 40
GAME = b'REAL-GAME-BYTES-' * 40
SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'import_bios.py'


@pytest.fixture
def symlinks(tmp_path):
    """Skip where links cannot be made; every test below plants one."""
    probe = tmp_path / 'symlink-probe'
    try:
        os.symlink(tmp_path, probe, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip('symlinks are not available here')
    probe.unlink()


@pytest.fixture
def secret(tmp_path, symlinks):
    """A readable file *outside* every folder in these tests."""
    path = tmp_path / 'outside' / 'secret.bin'
    path.parent.mkdir()
    path.write_bytes(SECRET)
    return path


@pytest.fixture
def game_dir(tmp_path):
    folder = tmp_path / 'library' / 'Some Game'
    folder.mkdir(parents=True)
    return folder


# --------------------------------------------------------------------------
# freshness: version.txt and friends
# --------------------------------------------------------------------------

def _facts(folder: Path) -> dict:
    from oneirodex.utils.freshness.local import detect_local_facts

    game = SimpleNamespace(name='Some Game', full_disk_path=str(folder), nfo_content=None, updates=[], extras=[])
    return detect_local_facts(game)


def test_freshness_reads_a_plain_version_file(game_dir):
    (game_dir / 'version.txt').write_text('1.4.2\n', encoding='utf-8')
    facts = _facts(game_dir)
    assert (facts['version'], facts['source'], facts['version_file']) == ('1.4.2', 'version_file', 'version.txt')


def test_freshness_never_reads_a_version_file_that_is_a_link(game_dir, tmp_path, symlinks):
    # The version lands in Game.local_version and the freshness payload, which
    # every member can read: ``version.txt -> /run/secrets/...`` must not.
    password = tmp_path / 'outside' / 'db_password'
    password.parent.mkdir()
    password.write_text('s3cr3t-Pa$$word-from-a-docker-secret\n', encoding='utf-8')
    os.symlink(password, game_dir / 'version.txt')
    facts = _facts(game_dir)
    assert facts['version'] is None
    assert facts['version_file'] is None
    assert 's3cr3t' not in repr(facts)


def test_freshness_skips_a_linked_version_file_and_uses_the_next_real_one(game_dir, secret):
    os.symlink(secret, game_dir / 'version.txt')
    (game_dir / 'build.txt').write_text('Build 77\n', encoding='utf-8')
    facts = _facts(game_dir)
    assert (facts['version'], facts['version_file']) == ('77', 'build.txt')


def test_freshness_ignores_a_blank_version_file(game_dir):
    # A blank file used to raise IndexError out of the whole freshness check.
    (game_dir / 'version.txt').write_text('  \n\n', encoding='utf-8')
    (game_dir / 'build.txt').write_text('', encoding='utf-8')
    (game_dir / 'product_version.txt').write_text('v2.0.1\n', encoding='utf-8')
    facts = _facts(game_dir)
    assert (facts['version'], facts['version_file']) == ('2.0.1', 'product_version.txt')


def test_freshness_does_not_read_a_game_folder_that_leads_out_of_the_library(tmp_path, symlinks, monkeypatch):
    from flask import Flask

    from oneirodex.utils import security

    library = tmp_path / 'library'
    library.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'version.txt').write_text('s3cr3t-token-1.2.3\n')
    os.symlink(outside, library / 'Some Game', target_is_directory=True)
    monkeypatch.setattr(security, 'get_allowed_base_directories', lambda app: [str(library)])

    with Flask('freshness-test').app_context():
        facts = _facts(library / 'Some Game')
    assert facts.get('version') is None


def test_freshness_version_past_the_read_cap_is_not_seen(game_dir):
    """Pins the cap itself: a version token after the first 4096 bytes is never read."""
    (game_dir / 'version.txt').write_bytes(b'\n' * 5000 + b'v9.9.9\n')
    assert _facts(game_dir).get('version') != '9.9.9'


def test_freshness_reads_only_the_start_of_a_version_file(game_dir):
    (game_dir / 'version.txt').write_bytes(b'x' * 100_000)
    facts = _facts(game_dir)
    assert facts['version'] == 'x' * 80, 'the first line is capped at 80 characters'


# --------------------------------------------------------------------------
# scripts/import_bios.py main()
# --------------------------------------------------------------------------

def _load_script():
    spec = importlib.util.spec_from_file_location('import_bios_script_main_under_test', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_cli(module, monkeypatch, source: Path, dest: Path, *extra: str) -> int:
    monkeypatch.setattr(
        'sys.argv', ['import_bios.py', '--source', str(source), '--dest', str(dest), '--apply', *extra]
    )
    return module.main()


def _swap_after_scan(module, monkeypatch, victims: list[str], secret: Path) -> None:
    """The share changes after the scan vetted the files."""
    real_scan = module.scan

    def scan_then_swap(source, wanted):
        found = {name: sorted(paths) for name, paths in real_scan(source, wanted).items()}
        for path in victims:
            os.unlink(path)
            os.symlink(secret, path)
        return found

    monkeypatch.setattr(module, 'scan', scan_then_swap)


@pytest.mark.parametrize('copies', [1, 2])
def test_import_bios_cli_does_not_copy_a_file_swapped_for_a_link_after_the_scan(
    tmp_path, secret, monkeypatch, capsys, copies
):
    module = _load_script()
    pack = tmp_path / 'pack'
    victims = []
    for index in range(copies):
        folder = pack / f'p{index}'
        folder.mkdir(parents=True)
        (folder / 'scph5501.bin').write_bytes(GAME)
        victims.append(str(folder / 'scph5501.bin'))
    _swap_after_scan(module, monkeypatch, victims, secret)
    dest = tmp_path / 'volume'

    rc = _run_cli(module, monkeypatch, pack, dest)

    out = capsys.readouterr().out
    assert not (dest / 'scph5501.bin').exists(), 'the link target must not reach the firmware volume'
    assert rc == 1, 'a refused file is not a clean run'
    assert 'not installed' in out
    assert 'scph5501.bin' in out


def test_import_bios_cli_installs_the_readable_copy_when_the_other_one_was_swapped(
    tmp_path, secret, monkeypatch, capsys
):
    module = _load_script()
    pack = tmp_path / 'pack'
    for name in ('a', 'b'):
        (pack / name).mkdir(parents=True)
        (pack / name / 'scph5501.bin').write_bytes(GAME)
    _swap_after_scan(module, monkeypatch, [str(pack / 'a' / 'scph5501.bin')], secret)
    dest = tmp_path / 'volume'

    rc = _run_cli(module, monkeypatch, pack, dest)

    assert rc == 0
    assert (dest / 'scph5501.bin').read_bytes() == GAME
    assert 'not installed' not in capsys.readouterr().out


def test_import_bios_cli_goes_on_after_a_refused_file(tmp_path, secret, monkeypatch, capsys):
    module = _load_script()
    pack = tmp_path / 'pack'
    pack.mkdir()
    (pack / 'scph5500.bin').write_bytes(GAME)
    (pack / 'scph5501.bin').write_bytes(GAME + b'!')
    # Files are installed in name order, so the refused one comes first.
    _swap_after_scan(module, monkeypatch, [str(pack / 'scph5500.bin')], secret)
    dest = tmp_path / 'volume'

    rc = _run_cli(module, monkeypatch, pack, dest)

    out = capsys.readouterr().out
    assert rc == 1
    assert (dest / 'scph5501.bin').read_bytes() == GAME + b'!', 'the file after the refused one is still copied'
    assert not (dest / 'scph5500.bin').exists()
    assert 'Copied 1 file(s)' in out
    assert 'scph5500.bin' in out and 'not installed' in out


def test_import_bios_cli_preview_reports_firmware_that_can_no_longer_be_read(
    tmp_path, secret, monkeypatch, capsys
):
    module = _load_script()
    pack = tmp_path / 'pack'
    for name in ('a', 'b'):
        (pack / name).mkdir(parents=True)
        (pack / name / 'scph5501.bin').write_bytes(GAME)
    _swap_after_scan(
        module, monkeypatch, [str(pack / 'a' / 'scph5501.bin'), str(pack / 'b' / 'scph5501.bin')], secret
    )
    dest = tmp_path / 'volume'
    monkeypatch.setattr(
        'sys.argv', ['import_bios.py', '--source', str(pack), '--dest', str(dest)]  # no --apply: a preview
    )

    rc = module.main()

    out = capsys.readouterr().out
    assert rc == 1, 'a copy that cannot be read is not a clean preview either'
    assert 'could not be read' not in out, 'the old fallback offered the link as the file to import'
    assert 'scph5501.bin' in out and 'not installed' in out
    assert 'Preview only' not in out, 'there is nothing to preview'
    assert not dest.exists()


def test_import_bios_cli_still_copies_plain_files(tmp_path, monkeypatch, capsys):
    module = _load_script()
    pack = tmp_path / 'pack'
    (pack / 'psx').mkdir(parents=True)
    (pack / 'psx' / 'scph5501.bin').write_bytes(GAME)
    os.utime(pack / 'psx' / 'scph5501.bin', (1_600_000_000, 1_600_000_000))
    dest = tmp_path / 'volume'

    assert _run_cli(module, monkeypatch, pack, dest) == 0

    assert (dest / 'scph5501.bin').read_bytes() == GAME
    assert int((dest / 'scph5501.bin').stat().st_mtime) == 1_600_000_000, 'the file keeps its timestamp'
    assert 'Copied 1 file(s)' in capsys.readouterr().out


def test_import_bios_cli_require_all_refuses_partial_install(tmp_path, monkeypatch, caplog):
    module = _load_script()
    pack = tmp_path / 'pack'
    pack.mkdir()
    (pack / 'scph5501.bin').write_bytes(GAME)
    dest = tmp_path / 'volume'
    monkeypatch.setattr(
        'sys.argv',
        ['import_bios.py', '--source', str(pack), '--dest', str(dest), '--apply', '--require-all'],
    )

    rc = module.main()

    assert rc == 2
    assert 'nothing was copied' in caplog.text.lower()
    assert not dest.exists()


@pytest.mark.parametrize('layout', ['dest_inside_source', 'hardlink'])
def test_import_bios_cli_never_overwrites_a_firmware_file_with_itself(tmp_path, monkeypatch, capsys, layout):
    """--overwrite with the installed file found as its own source used to open
    dest for writing first, truncating the very file it was about to read."""
    module = _load_script()
    pack = tmp_path / 'pack'
    if layout == 'dest_inside_source':
        dest = pack / 'bios'
        dest.mkdir(parents=True)
        (dest / 'scph5501.bin').write_bytes(GAME)
    else:
        dest = tmp_path / 'volume'
        dest.mkdir()
        (pack / 'psx').mkdir(parents=True)
        (dest / 'scph5501.bin').write_bytes(GAME)
        try:
            os.link(dest / 'scph5501.bin', pack / 'psx' / 'scph5501.bin')
        except OSError:
            pytest.skip('hard links are not available here')

    rc = _run_cli(module, monkeypatch, pack, dest, '--overwrite')

    assert rc == 0
    assert (dest / 'scph5501.bin').read_bytes() == GAME, 'the installed firmware is intact'
    assert 'already present' in capsys.readouterr().out


def test_copy_refuses_to_write_a_file_onto_itself(tmp_path):
    module = _load_script()
    (tmp_path / 'scph5501.bin').write_bytes(GAME)
    module._copy(str(tmp_path), str(tmp_path / 'scph5501.bin'), str(tmp_path / 'scph5501.bin'))
    assert (tmp_path / 'scph5501.bin').read_bytes() == GAME


# --------------------------------------------------------------------------
# sidecar metadata write
# --------------------------------------------------------------------------

def test_sidecar_write_swapped_for_a_link_after_the_check_does_not_write_through(
    game_dir, tmp_path, symlinks, monkeypatch
):
    # The write checks "is it a link / outside the folder" and then opens. A
    # share writer who plants the link between the two used to make the server
    # truncate and overwrite whatever the link named.
    import json

    from oneirodex.utils import local_metadata

    victim = tmp_path / 'outside' / 'precious.json'
    victim.parent.mkdir()
    victim.write_text(json.dumps({'igdb_id': 7, 'keep': 'me'}))
    sidecar = game_dir / 'oneirodex.json'
    real_within = local_metadata.is_path_within

    def check_then_swap(base, path):
        result = real_within(base, path)
        if str(path).endswith('oneirodex.json') and not os.path.lexists(path):
            os.symlink(victim, sidecar)
        return result

    monkeypatch.setattr(local_metadata, 'is_path_within', check_then_swap)

    local_metadata.write_local_metadata(str(game_dir), 123, game_title='X')

    assert os.path.islink(sidecar) is False, 'the planted link was replaced, not written through'
    assert json.loads(victim.read_text()) == {'igdb_id': 7, 'keep': 'me'}, 'the link target was not overwritten'
    monkeypatch.undo()
    assert local_metadata.read_local_metadata(str(game_dir))['igdb_id'] == 123


def test_sidecar_write_replaces_the_previous_file_and_leaves_no_temp_files(game_dir):
    from oneirodex.utils.local_metadata import read_local_metadata, write_local_metadata

    assert write_local_metadata(str(game_dir), 1, game_title='First') is True
    assert write_local_metadata(str(game_dir), 2, game_title='Second', manually_verified=True) is True

    saved = read_local_metadata(str(game_dir))
    assert (saved['igdb_id'], saved['title'], saved['manually_verified']) == (2, 'Second', True)
    assert sorted(p.name for p in game_dir.iterdir()) == ['oneirodex.json']


def test_sidecar_write_keeps_the_game_folders_timestamps(game_dir):
    """Freshness reads the folder mtime as 'updated locally'; our own sidecar
    write (a temp file renamed into place) must not look like a game update."""
    from oneirodex.utils.local_metadata import write_local_metadata

    os.utime(game_dir, ns=(1_600_000_000_000_000_000, 1_600_000_000_000_000_000))
    assert write_local_metadata(str(game_dir), 1, game_title='First') is True
    assert write_local_metadata(str(game_dir), 2, game_title='Second') is True
    assert game_dir.stat().st_mtime_ns == 1_600_000_000_000_000_000


def test_an_oversized_sidecar_is_ignored(game_dir):
    from oneirodex.utils.local_metadata import read_local_metadata

    (game_dir / 'oneirodex.json').write_text('{"igdb_id": 1, "pad": "' + 'x' * (300 * 1024) + '"}')
    assert read_local_metadata(str(game_dir)) is None


def test_sidecar_write_that_cannot_land_cleans_up_after_itself(game_dir):
    from oneirodex.utils.local_metadata import write_local_metadata

    (game_dir / 'oneirodex.json').mkdir()  # not something a file can replace
    assert write_local_metadata(str(game_dir), 5) is False
    assert sorted(p.name for p in game_dir.iterdir()) == ['oneirodex.json']
    assert (game_dir / 'oneirodex.json').is_dir()


def test_write_permission_probe_does_not_write_through_a_planted_link(game_dir, tmp_path, symlinks):
    # The probe writes a scratch file into every library folder it checks; a
    # link planted under that name used to be truncated and overwritten.
    from oneirodex.utils.local_metadata import check_write_permissions

    victim = tmp_path / 'outside' / 'precious.txt'
    victim.parent.mkdir()
    victim.write_text('keep me')
    os.symlink(victim, game_dir / '_oneirodex_write_test.tmp')

    assert check_write_permissions(str(game_dir)) == (True, '')

    assert victim.read_text() == 'keep me'
    assert list(game_dir.iterdir()) == [], 'the probe cleans up after itself'


def test_write_permission_probe_survives_a_leftover_from_an_interrupted_check(game_dir):
    from oneirodex.utils.local_metadata import check_write_permissions

    (game_dir / '_oneirodex_write_test.tmp').write_text('stale')

    assert check_write_permissions(str(game_dir)) == (True, '')
    assert list(game_dir.iterdir()) == []


def test_sidecar_read_swapped_for_a_link_after_the_check_is_not_followed(game_dir, tmp_path, symlinks, monkeypatch):
    import json

    from oneirodex.utils import local_metadata

    local_metadata.write_local_metadata(str(game_dir), 123, game_title='Mine')
    sidecar = game_dir / 'oneirodex.json'
    other = tmp_path / 'outside' / 'other.json'
    other.parent.mkdir()
    other.write_text(json.dumps({'igdb_id': 999, 'title': 'Not this game'}))
    real_resolve = local_metadata._resolve_metadata_path

    def resolve_then_swap(folder, name):
        found = real_resolve(folder, name)  # vetted as a plain file...
        sidecar.unlink()
        os.symlink(other, sidecar)  # ...and replaced before it is opened
        return found

    monkeypatch.setattr(local_metadata, '_resolve_metadata_path', resolve_then_swap)

    assert local_metadata.read_local_metadata(str(game_dir)) is None, 'the link target was read as this game'
