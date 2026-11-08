"""Run the actual startup shell with inert Python/server executables."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASH = 'C:/Program Files/Git/bin/bash.exe' if os.name == 'nt' else shutil.which('bash')


def run_startup(tmp_path, status=0, force=False, signal=False):
    if not BASH or not Path(BASH).exists():
        pytest.skip('Bash required')
    for name, content in {
        'python3': '#!/bin/bash\nexit "$INIT_STATUS"\n',
        'uvicorn': '''#!/bin/bash
echo "serving:$ONEIRODEX_MIGRATIONS_COMPLETE:$ONEIRODEX_INITIALIZATION_COMPLETE" > "$MARKER"
if [ "$SIGNAL_TEST" = 1 ]; then
  trap 'echo terminated >> "$MARKER"; exit 0' TERM
  while true; do sleep 0.05; done
fi
''',
    }.items():
        path = tmp_path / name
        path.write_text(content, encoding='utf-8', newline='\n')
        path.chmod(0o755)
    env = {**os.environ, 'INIT_STATUS': str(status), 'MARKER': str(tmp_path / 'marker'),
           'SIGNAL_TEST': '1' if signal else '0'}
    prefix = 'export PATH="$(cygpath -u "$1"):$PATH";' if os.name == 'nt' else 'export PATH="$1:$PATH";'
    command = prefix + 'exec bash "$2" "$3"'
    if signal:
        command = prefix + '''
bash "$2" & child=$!
for i in {1..100}; do [ -f "$MARKER" ] && break; sleep 0.05; done
kill -TERM "$child"
wait "$child"
'''
    result = subprocess.run([BASH, '-c', command, 'startup-test', str(tmp_path),
                             str(ROOT / 'startweb-docker.sh'), '--force-setup' if force else ''],
                            env=env, capture_output=True, text=True, timeout=15)
    marker = tmp_path / 'marker'
    return result, marker.read_text() if marker.exists() else ''


@pytest.mark.parametrize('force', [False, True])
def test_failed_initialization_never_starts_server(tmp_path, force):
    result, marker = run_startup(tmp_path, status=23, force=force)
    assert result.returncode == 23, result.stderr
    assert marker == ''


def test_success_sets_flags_before_serving(tmp_path):
    result, marker = run_startup(tmp_path)
    assert result.returncode == 0, result.stderr
    assert marker.strip() == 'serving:true:true'


def test_sigterm_reaches_server(tmp_path):
    result, marker = run_startup(tmp_path, signal=True)
    assert result.returncode == 0, result.stderr
    assert 'terminated' in marker


def test_entrypoint_executes_startup():
    entrypoint = (ROOT / 'entrypoint.sh').read_text(encoding='utf-8')

    assert 'APP_START_COMMAND=(/app/startweb-docker.sh "$@")' in entrypoint
    assert 'exec setpriv --no-new-privs --bounding-set=-all' in entrypoint


def test_entrypoint_migrates_library_ownership_and_rejects_root_app_identity():
    entrypoint = (ROOT / 'entrypoint.sh').read_text(encoding='utf-8')

    assert 'chown -R "${APP_UID}:${APP_GID}" "${APP_LIBRARY_DIR}"' in entrypoint
    assert 'PUID=0 is not supported for the app process' in entrypoint
    assert '--reuid="${APP_UID}" --regid="${APP_GID}" --clear-groups' in entrypoint
    assert '/app/oneirodex/static/library|/config/library)' in entrypoint
    assert '/app|/app/*|/config|/config/*|/storage|/storage/*' in entrypoint
    assert 'APP_LIBRARY_ID="$(stat -c \'%d-%i\' "${APP_LIBRARY_DIR}")"' in entrypoint
    assert 'OWNER_MARKER="${APP_LIBRARY_DIR}/.oneirodex-library-owner-${APP_UID}-${APP_GID}-${APP_LIBRARY_ID}-v1"' in entrypoint


def test_entrypoint_passes_database_settings_as_environment_not_python_source():
    entrypoint = (ROOT / 'entrypoint.sh').read_text(encoding='utf-8')

    assert 'DB_HOST="$DB_HOST" DB_USER="$DB_USER" DB_PORT="$DB_PORT" python3 -c' in entrypoint
    assert "os.environ.get('DATABASE_HOST', '${DB_HOST}')" not in entrypoint
    assert "os.environ.get('DATABASE_PORT', '${DB_PORT}')" not in entrypoint
    assert "os.environ.get('POSTGRES_USER', '${DB_USER}')" not in entrypoint
