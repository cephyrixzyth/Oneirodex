"""The docs capture instance must not launch product background workers."""


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
