"""The free-ROM fetcher unpacks zips and refuses a file that changed upstream."""
import importlib.util
import io
import zipfile
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    'fetch_free_roms', Path(__file__).resolve().parents[1] / 'scripts' / 'fetch-free-roms.py'
)
fetch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch)


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_picks_the_rom_looking_member_not_the_readme():
    name, data = fetch.extract_rom_from_zip(_zip({'README.txt': b'hi', 'game/JUMTRO.LNX': b'ROM'}))
    assert name == 'game/JUMTRO.LNX' and data == b'ROM'


def test_a_named_member_wins_and_a_missing_one_is_an_error():
    z = _zip({'a.bin': b'A', 'b.bin': b'B'})
    assert fetch.extract_rom_from_zip(z, 'b.bin')[1] == b'B'
    with pytest.raises(ValueError, match='no member'):
        fetch.extract_rom_from_zip(z, 'c.bin')


def test_a_zip_with_no_rom_is_reported_not_saved():
    with pytest.raises(ValueError, match='no ROM-looking'):
        fetch.extract_rom_from_zip(_zip({'notes.txt': b'x'}))


def test_download_unzips_and_checks_the_pinned_hash(tmp_path, monkeypatch):
    import hashlib

    payload = _zip({'x.gba': b'ROMBYTES'})
    monkeypatch.setattr(fetch, 'fetch_bytes', lambda url, timeout=90.0: payload)
    dest = tmp_path / 'gba' / 'x.gba'
    fetch.download('https://example.invalid/x.zip', dest, archive='zip',
                   sha256=hashlib.sha256(payload).hexdigest())
    assert dest.read_bytes() == b'ROMBYTES'

    with pytest.raises(ValueError, match='sha256 mismatch'):
        fetch.download('https://example.invalid/x.zip', tmp_path / 'y.gba', archive='zip', sha256='0' * 64)


def test_manifest_parser_reads_the_new_fields(tmp_path):
    path = tmp_path / 'm.yaml'
    path.write_text(
        'version: 1\nroms:\n  - id: a\n    platform: lynx\n    filename: a.lnx\n'
        '    url: https://x.invalid/a.zip\n    archive: zip\n    member: a.lnx\n',
        encoding='utf-8',
    )
    entry = fetch.load_simple_manifest(path)['roms'][0]
    assert (entry['archive'], entry['member']) == ('zip', 'a.lnx')


def test_unknown_rom_id_is_reported_before_download(tmp_path, capsys):
    manifest = tmp_path / 'm.yaml'
    manifest.write_text(
        'version: 1\nroms:\n  - id: known\n    platform: lynx\n    filename: a.lnx\n'
        '    url: https://x.invalid/a.zip\n',
        encoding='utf-8',
    )

    with pytest.raises(SystemExit) as exc:
        fetch.main(['--manifest', str(manifest), '--id', 'missing', '--out', str(tmp_path)])

    assert exc.value.code == 2
    assert 'unknown ROM id(s): missing' in capsys.readouterr().err
