"""Filesystem-only regressions for uploaded theme archives."""

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
from pathlib import Path
from threading import Barrier
import zipfile

from flask import Flask
import pytest

from oneirodex.utils import themes


def _theme_zip(
    name: str, *, css: str | None = None, extra: dict[str, bytes] | None = None,
) -> BytesIO:
    data = BytesIO()
    with zipfile.ZipFile(data, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('theme.json', json.dumps({
            'name': name,
            'description': 'Test theme',
            'author': 'Test',
            'release_date': '2026-01-01',
        }))
        archive.writestr('css/style.css', css if css is not None else name)
        for member, content in (extra or {}).items():
            archive.writestr(member, content)
    data.seek(0)
    return data


@pytest.fixture
def manager(tmp_path, monkeypatch):
    upload = tmp_path / 'uploads'
    upload.mkdir()
    library = tmp_path / 'library'
    monkeypatch.setattr(themes, 'library_dir', lambda _root: str(library))
    monkeypatch.setattr(themes, 'flash', lambda *_args: None)
    app = Flask(__name__)
    app.config['UPLOAD_FOLDER'] = str(upload)
    return themes.ThemeManager(app)


def test_upload_rejects_expanded_limit_before_extracting(manager, monkeypatch):
    monkeypatch.setattr(themes, 'MAX_THEME_EXPANDED_BYTES', 1024)
    messages = []
    monkeypatch.setattr(themes, 'flash', lambda message, level: messages.append((message, level)))
    archive = _theme_zip('Too Large', extra={'large.txt': b'x' * 2048})
    original_extractall = zipfile.ZipFile.extractall
    extracted = []

    def track_extractall(self, *args, **kwargs):
        extracted.append(True)
        return original_extractall(self, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, 'extractall', track_extractall)
    with manager.app.test_request_context():
        assert manager.upload_theme(archive) is None
    assert not extracted
    assert any('100MB limit' in message for message, _ in messages)
    assert not list(Path(manager.app.config['UPLOAD_FOLDER']).glob('temp_theme_*'))


def test_upload_rejects_member_count_before_extracting(manager, monkeypatch):
    monkeypatch.setattr(themes, 'MAX_THEME_ZIP_MEMBERS', 2)
    archive = _theme_zip('Too Many', extra={'extra.txt': b'extra'})
    with manager.app.test_request_context():
        assert manager.upload_theme(archive) is None
    assert not list(Path(manager.theme_folder).iterdir())


def test_upload_rejects_traversal_before_extracting(manager, monkeypatch):
    archive = _theme_zip('Unsafe', extra={'css/../outside.css': b'bad'})
    extracted = []
    original_extractall = zipfile.ZipFile.extractall

    def track_extractall(self, *args, **kwargs):
        extracted.append(True)
        return original_extractall(self, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, 'extractall', track_extractall)
    with manager.app.test_request_context():
        assert manager.upload_theme(archive) is None
    assert not extracted
    assert not list(Path(manager.app.config['UPLOAD_FOLDER']).glob('temp_theme_*'))


def test_overlapping_uploads_keep_their_own_theme_files(manager, monkeypatch):
    barrier = Barrier(2)
    original_extractall = zipfile.ZipFile.extractall

    def synchronized_extractall(self, *args, **kwargs):
        result = original_extractall(self, *args, **kwargs)
        barrier.wait(timeout=5)
        return result

    monkeypatch.setattr(zipfile.ZipFile, 'extractall', synchronized_extractall)

    def upload(name):
        with manager.app.test_request_context():
            return manager.upload_theme(_theme_zip(name))

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(upload, 'First Theme')
        second = pool.submit(upload, 'Second Theme')
        assert first.result(timeout=10)['name'] == 'First Theme'
        assert second.result(timeout=10)['name'] == 'Second Theme'

    root = Path(manager.theme_folder)
    assert (root / 'First_Theme' / 'css' / 'style.css').read_text() == 'First Theme'
    assert (root / 'Second_Theme' / 'css' / 'style.css').read_text() == 'Second Theme'
    assert not list(Path(manager.app.config['UPLOAD_FOLDER']).glob('temp_theme_*'))


def test_overlapping_uploads_with_same_name_publish_only_one(manager, monkeypatch):
    barrier = Barrier(2)
    original_extractall = zipfile.ZipFile.extractall

    def synchronized_extractall(self, *args, **kwargs):
        result = original_extractall(self, *args, **kwargs)
        barrier.wait(timeout=5)
        return result

    monkeypatch.setattr(zipfile.ZipFile, 'extractall', synchronized_extractall)

    def upload(marker):
        with manager.app.test_request_context():
            return marker, manager.upload_theme(_theme_zip('Same Theme', css=marker))

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(upload, 'first upload')
        second = pool.submit(upload, 'second upload')
        results = [first.result(timeout=10), second.result(timeout=10)]

    accepted = [marker for marker, result in results if result is not None]
    assert len(accepted) == 1
    published = Path(manager.theme_folder) / 'Same_Theme'
    assert (published / 'css' / 'style.css').read_text() == accepted[0]
    assert sorted(path.name for path in published.iterdir()) == ['css', 'theme.json']
    assert not list(Path(manager.app.config['UPLOAD_FOLDER']).glob('temp_theme_*'))
