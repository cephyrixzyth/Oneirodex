"""INSP-1 / H4e: the community save-location manifest -- compact index, lookups,
daily fetch. Mocked transport; the fetch stays off under pytest unless opted in."""
from __future__ import annotations

import json
import os
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from oneirodex.utils import save_paths as sp

MANIFEST_YAML = b"""
Hollow Knight:
  files:
    <winAppData>/../LocalLow/Team Cherry/Hollow Knight:
      tags: [save, config]
      when:
        - os: windows
    <xdgConfig>/unity3d/Team Cherry/Hollow Knight:
      tags: [save]
      when:
        - os: linux
    <base>/hollow_knight_Data:
      tags: [config]
  steam:
    id: 367520
Some Config-Only Game:
  files:
    <winDocuments>/thing.ini:
      tags: [config]
Stardew Valley:
  files:
    <winAppData>/StardewValley/Saves:
      tags: [save]
      when:
        - os: windows
          store: steam
        - os: windows
          store: gog
  steam:
    id: 413150
"""


def test_build_index_keeps_only_save_tagged_paths_with_constraints():
    index = sp.build_index(sp.parse_manifest_yaml(MANIFEST_YAML))
    assert index['count'] == 2  # the config-only game has no save row
    hk = index['by_name']['hollow knight']
    assert hk['steam_id'] == '367520'
    assert [(p['path'], p['os']) for p in hk['paths']] == [
        ('<winAppData>/../LocalLow/Team Cherry/Hollow Knight', 'windows'),
        ('<xdgConfig>/unity3d/Team Cherry/Hollow Knight', 'linux'),
    ]
    sv = index['by_name']['stardew valley']
    assert [(p['os'], p['store']) for p in sv['paths']] == [('windows', 'steam'), ('windows', 'gog')]
    assert index['by_steam']['413150'] == 'stardew valley'
    with pytest.raises(ValueError):
        sp.build_index({'Only Config': {'files': {'<home>/x': {'tags': ['config']}}}})
    with pytest.raises(ValueError):
        sp.build_index([])


@pytest.fixture
def indexed(tmp_path, monkeypatch):
    monkeypatch.setenv('SAVE_PATHS_CACHE_DIR', str(tmp_path))
    monkeypatch.delenv('ENABLE_SAVE_PATHS', raising=False)
    (tmp_path / 'manifest.index.json').write_text(json.dumps(sp.build_index(sp.parse_manifest_yaml(MANIFEST_YAML))), encoding='utf-8')
    sp.load_index(force=True)
    yield tmp_path
    sp.load_index(force=True)


def _game(name, steam=None, platform='PCWIN'):
    library = SimpleNamespace(platform=SimpleNamespace(name=platform)) if platform else None
    return SimpleNamespace(name=name, steam_app_id=steam, library=library)


def test_lookup_by_steam_then_name_and_pc_only(indexed):
    assert sp.lookup(steam_app_id=413150)['name'] == 'Stardew Valley'
    assert sp.lookup(name='HOLLOW  Knight!')['steam_id'] == '367520'
    assert sp.lookup(name='Unknown Game') is None
    assert sp.save_paths_for(_game('Hollow Knight'))[0]['os'] == 'windows'
    assert sp.save_paths_for(_game('Anything', steam=413150))[1]['store'] == 'gog'
    assert sp.save_paths_for(_game('Hollow Knight', platform='SNES')) is None
    assert sp.save_paths_for(_game('Some Config-Only Game')) is None
    summary = sp.status_summary()
    assert summary['configured'] is True and summary['count'] == 2


def test_disabled_or_missing_index_is_none(tmp_path, monkeypatch):
    monkeypatch.setenv('SAVE_PATHS_CACHE_DIR', str(tmp_path / 'nothing'))
    sp.load_index(force=True)
    assert sp.lookup(name='Hollow Knight') is None and sp.status_summary()['configured'] is False
    monkeypatch.setenv('ENABLE_SAVE_PATHS', 'false')
    assert sp.save_paths_for(_game('Hollow Knight')) is None


def test_refresh_is_off_under_pytest_unless_opted_in(app, tmp_path, monkeypatch):
    monkeypatch.setenv('SAVE_PATHS_CACHE_DIR', str(tmp_path))
    monkeypatch.delenv('SAVE_PATHS_IN_TESTS', raising=False)
    with app.app_context(), patch.object(sp, 'safe_request') as req:
        assert sp.refresh_if_stale(force=True) is False
        req.assert_not_called()


def test_refresh_builds_the_index_and_keeps_it_on_failure(app, tmp_path, monkeypatch):
    monkeypatch.setenv('SAVE_PATHS_CACHE_DIR', str(tmp_path))
    monkeypatch.setenv('SAVE_PATHS_IN_TESTS', '1')
    monkeypatch.delenv('ENABLE_SAVE_PATHS', raising=False)
    sp.load_index(force=True)
    good = SimpleNamespace(status_code=200, content=MANIFEST_YAML)
    with app.app_context(), patch.object(sp, 'safe_request', return_value=good) as req:
        assert sp.refresh_if_stale() is True
        assert req.call_args.kwargs['validator'] is sp.validate_user_outbound_http_url
        assert req.call_args.kwargs['stream'] is True
    assert (tmp_path / 'manifest.index.json').exists() and (tmp_path / 'manifest.yaml').exists()
    assert sp.lookup(steam_app_id=367520)['name'] == 'Hollow Knight'
    before = (tmp_path / 'manifest.index.json').read_bytes()

    with app.app_context(), patch.object(sp, 'safe_request') as req:
        assert sp.refresh_if_stale() is False  # fresh
        req.assert_not_called()
    old = time.time() - sp.CACHE_TTL_SECONDS - 5
    os.utime(tmp_path / 'manifest.index.json', (old, old))
    for bad in (SimpleNamespace(status_code=503, content=b''), SimpleNamespace(status_code=200, content=b'- not: a mapping\n')):
        with app.app_context(), patch.object(sp, 'safe_request', return_value=bad):
            assert sp.refresh_if_stale() is False
        assert (tmp_path / 'manifest.index.json').read_bytes() == before
    with app.app_context(), patch.object(sp, 'safe_request', side_effect=OSError('offline')):
        assert sp.refresh_if_stale() is False
    sp.load_index(force=True)
