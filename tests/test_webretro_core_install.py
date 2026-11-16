"""The default WebRetro download path is locked to reviewed file hashes."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from oneirodex import platform
from oneirodex.utils import webretro_core_install as installer


def test_core_hash_manifest_covers_default_core_pairs():
    hashes = installer.load_core_hashes()

    expected_names = {
        f'{core_id}{suffix}'
        for core_id in platform.WEBRETR_INSTALLED_CORES
        for suffix in installer.CORE_SUFFIXES
    }
    assert set(hashes) == expected_names
    assert len(hashes) == 48


def test_manual_default_fetchers_verify_both_files_before_replacement():
    root = Path(__file__).resolve().parents[1]
    shell = (root / 'scripts' / 'fetch-webretro-cores.sh').read_text(encoding='utf-8')
    powershell = (root / 'scripts' / 'fetch-webretro-cores.ps1').read_text(encoding='utf-8')

    assert 'scripts/webretro-cores.sha256' in shell
    assert 'sha256sum' in shell and 'shasum -a 256' in shell
    assert shell.index('"$js_actual" != "$js_expected"') < shell.index('mv -f -- "$js_tmp"')
    assert 'scripts\\webretro-cores.sha256' in powershell
    assert 'Get-FileHash -LiteralPath $jsTemp -Algorithm SHA256' in powershell
    assert powershell.index('$jsActual -ne $jsExpected') < powershell.index('Move-Item -LiteralPath $jsTemp')


def test_core_hash_manifest_rejects_duplicate_or_malformed_entries(tmp_path: Path):
    manifest = tmp_path / 'webretro-cores.sha256'
    manifest.write_text(
        f"{'a' * 64}  nestopia_libretro.js\n"
        f"{'b' * 64}  nestopia_libretro.js\n",
        encoding='ascii',
    )

    with pytest.raises(ValueError, match='Invalid WebRetro SHA-256 manifest entry'):
        installer.load_core_hashes(manifest)


def test_download_hash_mismatch_preserves_existing_pair_and_cleans_staging(
    tmp_path: Path, monkeypatch,
):
    core_id = 'nestopia'
    good_js = b'j' * installer.MIN_CORE_BYTES
    good_wasm = b'w' * installer.MIN_CORE_BYTES
    bad_wasm = b'x' * installer.MIN_CORE_BYTES
    monkeypatch.setattr(installer, 'load_core_hashes', lambda: {
        f'{core_id}_libretro.js': hashlib.sha256(good_js).hexdigest(),
        f'{core_id}_libretro.wasm': hashlib.sha256(good_wasm).hexdigest(),
    })
    monkeypatch.setattr(
        installer,
        '_fetch',
        lambda url: good_js if url.endswith('.js') else bad_wasm,
    )
    js_path = tmp_path / f'{core_id}_libretro.js'
    wasm_path = tmp_path / f'{core_id}_libretro.wasm'
    js_path.write_bytes(b'previous loader')
    wasm_path.write_bytes(b'previous wasm')

    with pytest.raises(ValueError, match='failed its SHA-256 integrity check'):
        installer.install_core(core_id, tmp_path)

    assert js_path.read_bytes() == b'previous loader'
    assert wasm_path.read_bytes() == b'previous wasm'
    assert list(tmp_path.glob('*.part')) == []
    assert list(tmp_path.glob('.*.part')) == []


def test_valid_download_replaces_both_files_only_after_verification(tmp_path: Path, monkeypatch):
    core_id = 'nestopia'
    payloads = {
        f'{core_id}_libretro.js': b'j' * installer.MIN_CORE_BYTES,
        f'{core_id}_libretro.wasm': b'w' * installer.MIN_CORE_BYTES,
    }
    monkeypatch.setattr(
        installer,
        'load_core_hashes',
        lambda: {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()},
    )
    monkeypatch.setattr(
        installer,
        '_fetch',
        lambda url: payloads[url.rsplit('/', 1)[-1]],
    )

    assert installer.install_core(core_id, tmp_path) is True
    assert (tmp_path / f'{core_id}_libretro.js').read_bytes() == payloads[
        f'{core_id}_libretro.js'
    ]
    assert (tmp_path / f'{core_id}_libretro.wasm').read_bytes() == payloads[
        f'{core_id}_libretro.wasm'
    ]
    assert list(tmp_path.glob('.*.part')) == []


def test_core_id_cannot_escape_the_cores_directory(tmp_path: Path):
    with pytest.raises(ValueError, match='Invalid WebRetro core ID'):
        installer.install_core('../outside', tmp_path)
    assert list(tmp_path.iterdir()) == []
