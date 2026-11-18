# tests/test_utils_worker_caps.py

from oneirodex.models import GlobalSettings
from oneirodex.utils.server_settings import MAX_SCAN_THREADS, SERVER_DEFAULTS as DEFAULT_SETTINGS
from oneirodex.utils.worker_caps import (
    clamp_image_download_batch,
    clamp_image_download_threads,
    clamp_scan_threads,
    iter_chunks,
)
import pytest

pytestmark = pytest.mark.integration  # A3.1: kept out of the fast `-m "not integration"` core -- background worker cap logic.


def test_clamp_scan_threads_respects_cap(monkeypatch):
    monkeypatch.delenv('ONEIRODEX_SCAN_THREAD_CAP', raising=False)
    monkeypatch.delenv('ONEIRODEX_SCAN_THREAD_CAP', raising=False)
    assert clamp_scan_threads(99) == 4
    assert clamp_scan_threads(1) == 1
    assert clamp_scan_threads(None) == 1


def test_clamp_scan_threads_env_override(monkeypatch):
    monkeypatch.delenv('ONEIRODEX_SCAN_THREAD_CAP', raising=False)
    monkeypatch.setenv('ONEIRODEX_SCAN_THREAD_CAP', '2')
    assert clamp_scan_threads(8) == 2


def test_clamp_scan_threads_oneirodex_prefix_wins(monkeypatch):
    monkeypatch.setenv('ONEIRODEX_SCAN_THREAD_CAP', '8')
    monkeypatch.setenv('ONEIRODEX_SCAN_THREAD_CAP', '2')
    assert clamp_scan_threads(8) == 2


def test_clamp_image_threads_and_batch(monkeypatch):
    monkeypatch.delenv('ONEIRODEX_IMAGE_DOWNLOAD_THREAD_CAP', raising=False)
    monkeypatch.delenv('ONEIRODEX_IMAGE_DOWNLOAD_BATCH_CAP', raising=False)
    monkeypatch.delenv('ONEIRODEX_IMAGE_DOWNLOAD_THREAD_CAP', raising=False)
    monkeypatch.delenv('ONEIRODEX_IMAGE_DOWNLOAD_BATCH_CAP', raising=False)
    assert clamp_image_download_threads(20) == 4
    assert clamp_image_download_batch(999) == 100


def test_unraid_safe_stored_defaults():
    """Ops Wave 1: new-row / API defaults stay Unraid-safe; caps remain separate."""
    assert GlobalSettings.scan_thread_count.default.arg == 1
    assert GlobalSettings.turbo_download_threads.default.arg == 4
    assert GlobalSettings.turbo_download_batch_size.default.arg == 100
    assert DEFAULT_SETTINGS['scanThreadCount'] == 1
    assert DEFAULT_SETTINGS['turboDownloadThreads'] == 4
    assert DEFAULT_SETTINGS['turboDownloadBatchSize'] == 100
    assert MAX_SCAN_THREADS == 4


def test_iter_chunks():
    assert list(iter_chunks([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]
