"""The docs capture instance must not launch product background workers."""


def test_capture_image_retries_atomic_replace_and_keeps_last_good_file(tmp_path, monkeypatch):
    import os

    from scripts import capture_docs_media

    target = tmp_path / "capture.png"
    target.write_bytes(b"old-good-image")
    real_replace = os.replace
    calls = 0

    def transient_replace(source, destination):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError(22, "transient replace failure")
        return real_replace(source, destination)

    monkeypatch.setattr(capture_docs_media.os, "replace", transient_replace)

    capture_docs_media._write_screenshot_atomically(target, b"new-image")

    assert calls == 2
    assert target.read_bytes() == b"new-image"
    assert list(tmp_path.glob(".capture.*.tmp")) == []


def test_capture_image_preserves_last_good_file_after_repeated_replace_failure(
    tmp_path, monkeypatch,
):
    import os

    import pytest

    from scripts import capture_docs_media

    target = tmp_path / "capture.png"
    target.write_bytes(b"old-good-image")
    calls = 0

    def failing_replace(_source, _destination):
        nonlocal calls
        calls += 1
        raise OSError(22, "persistent replace failure")

    monkeypatch.setattr(capture_docs_media.os, "replace", failing_replace)

    with pytest.raises(OSError, match="persistent replace failure"):
        capture_docs_media._write_screenshot_atomically(target, b"new-image")

    assert calls == 3
    assert target.read_bytes() == b"old-good-image"
    assert list(tmp_path.glob(".capture.*.tmp")) == []


def test_readme_asset_sync_uses_atomic_replace_and_preserves_existing_file(
    tmp_path, monkeypatch,
):
    import os

    from scripts import capture_docs_media

    source = tmp_path / "source.png"
    source.write_bytes(b"new-readme-image")
    destination_dir = tmp_path / "readme"
    destination_dir.mkdir()
    destination = destination_dir / "screenshot.png"
    destination.write_bytes(b"old-good-image")
    real_replace = os.replace
    calls = 0

    def transient_replace(src, dest):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError(22, "transient replace failure")
        return real_replace(src, dest)

    monkeypatch.setattr(capture_docs_media, "README_ASSETS", destination_dir)
    monkeypatch.setattr(capture_docs_media, "ROOT", tmp_path)
    monkeypatch.setattr(capture_docs_media.os, "replace", transient_replace)

    capture_docs_media._sync_readme(source, "screenshot.png")

    assert calls == 2
    assert destination.read_bytes() == b"new-readme-image"
    assert list(destination_dir.glob(".screenshot.*.tmp")) == []


def test_capture_environment_disables_background_workers(tmp_path, monkeypatch):
    from scripts import serve_capture

    env_file = tmp_path / ".env.capture.local"
    monkeypatch.setattr(serve_capture, "ENV_FILE", env_file)

    serve_capture.write_env()

    settings = {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in env_file.read_text(encoding="utf-8").splitlines()
        if "=" in line
    }
    assert settings["ONEIRODEX_ENABLE_BACKGROUND_WORKERS"] == "false"


def test_capture_login_waits_for_native_spa_redirect(monkeypatch):
    from scripts import capture_common

    class Field:
        def __init__(self, page):
            self.page = page

        def count(self):
            return 1

        def fill(self, _value):
            pass

        def press(self, _key):
            self.page.url = f"{capture_common.BASE}/discover"

    class Page:
        url = ""

        def goto(self, url, **_kwargs):
            self.url = url

        def locator(self, _selector):
            return Field(self)

        def wait_for_function(self, _predicate, *, timeout):
            assert timeout == 10_000
            assert self.url.endswith("/discover")

    assert capture_common.login(Page()) is True
