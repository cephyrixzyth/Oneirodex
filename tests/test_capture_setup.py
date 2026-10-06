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
