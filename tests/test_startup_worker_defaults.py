from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_native_server_entrypoints_default_to_one_uvicorn_worker():
    windows = (ROOT / 'startweb_windows.cmd').read_text(encoding='utf-8')
    unix = (ROOT / 'startweb.sh').read_text(encoding='utf-8')

    assert 'if not defined UVICORN_WORKERS set UVICORN_WORKERS=1' in windows
    assert '--workers %UVICORN_WORKERS%' in windows
    assert 'WORKERS="${UVICORN_WORKERS:-1}"' in unix
    assert '--workers "$WORKERS"' in unix
