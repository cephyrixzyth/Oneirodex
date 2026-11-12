"""Native configuration must survive reinstall and reach runtime intact."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which('pwsh') or shutil.which('powershell')
BASH = ('C:/Program Files/Git/bin/bash.exe' if os.name == 'nt' else shutil.which('bash'))
PRIOR = (
    b'SECRET_KEY=synthetic-retained-config-key-not-production\n'
    b'PORT=5006\nONEIRODEX_OPERATOR_TEST_FLAG=preserve-me\n'
)


@pytest.mark.skipif(not POWERSHELL, reason='PowerShell required for actual installer orchestration')
@pytest.mark.parametrize('mode', ['fresh', 'preserve', 'force'])
def test_windows_installer_validates_effective_config_and_retains_operator_values(tmp_path, mode):
    stage, result = tmp_path / 'owned-install', tmp_path / 'result.json'
    command = [
        POWERSHELL, '-NoProfile', '-NonInteractive', '-File',
        str(ROOT / 'tests/fixtures/native_installer_config.ps1'),
        '-InstallScript', str(ROOT / 'install-windows.ps1'),
        '-StageRoot', str(stage), '-ResultPath', str(result),
    ]
    if mode != 'fresh':
        command.append('-ExistingConfig')
    if mode == 'force':
        command.append('-ForceConfig')
    run = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=30)
    outcome = json.loads(result.read_text(encoding='utf-8-sig'))
    assert run.returncode == 0, outcome
    assert outcome['validated'] and outcome['failure'] is None
    if mode == 'preserve':
        assert outcome['existing_bytes_preserved']
        assert outcome['backup_count'] == 0
        assert outcome['summary_preserved_notice']
        assert not outcome['summary_mentions_requested_port']
        assert not outcome['summary_mentions_requested_games']
    else:
        assert outcome['summary_mentions_requested_port']
        assert outcome['summary_mentions_requested_games']
        assert outcome['backup_count'] == (1 if mode == 'force' else 0)
        if mode == 'force':
            assert outcome['backup_matches_prior']
    assert not outcome['system_installation_performed']
    assert not outcome['database_connection_attempted']
    assert not outcome['app_launched']


@pytest.mark.skipif(not POWERSHELL, reason='PowerShell required for actual installer orchestration')
def test_windows_invalid_retained_config_stops_before_summary_without_repair(tmp_path):
    result = tmp_path / 'result.json'
    run = subprocess.run(
        [POWERSHELL, '-NoProfile', '-NonInteractive', '-File',
         str(ROOT / 'tests/fixtures/native_installer_config.ps1'),
         '-InstallScript', str(ROOT / 'install-windows.ps1'),
         '-StageRoot', str(tmp_path / 'owned-invalid-install'), '-ResultPath', str(result),
         '-ExistingConfig', '-InvalidExistingConfig'],
        capture_output=True, text=True, encoding='utf-8', timeout=30,
    )
    outcome = json.loads(result.read_text(encoding='utf-8-sig'))
    assert run.returncode != 0
    assert not outcome['validated']
    assert outcome['failure'] == 'SYNTHETIC_SECRET_MISSING_AT_VALIDATION'
    assert outcome['existing_bytes_preserved']
    assert outcome['backup_count'] == 0
    assert 'summary-without-app-launch' not in outcome['events']
    assert not outcome['app_launched']


@pytest.mark.skipif(not BASH or not Path(BASH).is_file(), reason='Bash required')
@pytest.mark.parametrize('installer', ['install-linux.sh', 'install-macos.sh'])
@pytest.mark.parametrize('mode', ['fresh', 'preserve', 'force'])
def test_posix_config_preservation_force_backup_and_persisted_port(tmp_path, installer, mode):
    source = (ROOT / installer).read_text(encoding='utf-8')
    if installer == 'install-macos.sh':
        assert source.rstrip().endswith('main "$@"')
        source = source.rstrip()[:-len('main "$@"')]
    # Linux's entry guard is false when sourced by native-config-contract below.
    declarations = tmp_path / 'source-declarations.sh'
    declarations.write_text(source, encoding='utf-8', newline='\n')
    games = tmp_path / 'games'
    games.mkdir()
    env_file = tmp_path / '.env'
    if mode != 'fresh':
        env_file.write_bytes(PRIOR)
        env_file.chmod(0o600)
    script = '''
source "$1"
SCRIPT_DIR="$2"
LOG_FILE="$2/install.log"
GAMES_DIR="$2/games"
LIBRARY_ROOTS="Synthetic=$2/games"
DB_PASSWORD="synthetic-test-only"
DB_USER="review"
DB_NAME="oneirodex_installer_test"
TEST_DB_NAME="oneirodex_installer_tests"
CUSTOM_PORT=6120
FORCE_INSTALL="$3"
DEV_MODE=false
SKIP_DB=true
if [ "$4" = "install-linux.sh" ]; then backup_existing_config; fi
configure_application
show_summary <<< n
'''
    run = subprocess.run(
        [BASH, '--noprofile', '--norc', '-c', script, 'native-config-contract',
         declarations.as_posix(), tmp_path.as_posix(), 'true' if mode == 'force' else 'false',
         installer],
        capture_output=True, text=True, encoding='utf-8', timeout=30,
    )
    assert run.returncode == 0, run.stderr
    values = dict(
        line.split('=', 1) for line in env_file.read_text(encoding='utf-8').splitlines()
        if '=' in line and not line.startswith('#')
    )
    backups = list(tmp_path.glob('.env.backup.*'))
    if mode == 'preserve':
        assert env_file.read_bytes() == PRIOR
        assert not backups
        assert 'http://localhost:6120' not in run.stdout
        assert 'preserv' in run.stdout.lower()
    else:
        assert values.get('SECRET_KEY')
        assert values.get('PORT') == '6120'
        assert 'http://localhost:6120' in run.stdout
        assert len(backups) == (1 if mode == 'force' else 0)
        if mode == 'force':
            assert backups[0].read_bytes() == PRIOR
    if mode != 'fresh':
        assert values['SECRET_KEY'] == 'synthetic-retained-config-key-not-production'
    if os.name != 'nt':
        assert env_file.stat().st_mode & 0o777 == 0o600
        assert declarations.stat().st_mode & 0o111


@pytest.mark.skipif(os.name != 'nt', reason='Actual Windows batch parser')
def test_windows_launcher_retains_complete_values_after_first_equals(tmp_path):
    (tmp_path / 'venv/Scripts').mkdir(parents=True)
    (tmp_path / 'bin').mkdir()
    launcher = tmp_path / 'startweb_windows.cmd'
    launcher.write_bytes((ROOT / 'startweb_windows.cmd').read_bytes())
    (tmp_path / 'venv/Scripts/activate.bat').write_text('@exit /b 0\n', encoding='utf-8')
    key = 'synthetic-retained-signing-key-with-padding==tail='
    (tmp_path / '.env').write_text(
        'DATABASE_URL=postgresql://review:synthetic@127.0.0.1:1/oneirodex_parser_test\n'
        'PORT=6120\nSECRET_KEY=' + key + '\nONEIRODEX_OPERATOR_TEST_FLAG=left=right\n',
        encoding='utf-8',
    )
    # Inert startup before application imports; only the final capture runs.
    (tmp_path / 'sitecustomize.py').write_text(
        "import os,sys\nif not sys.argv[0].endswith('capture_env.py'):os._exit(0)\n",
        encoding='utf-8',
    )
    capture = tmp_path / 'capture.json'
    (tmp_path / 'bin/capture_env.py').write_text(
        "import hashlib,json,os\nfrom pathlib import Path\n"
        "result={'port':os.getenv('PORT'),'key':hashlib.sha256(os.getenv('SECRET_KEY','').encode()).hexdigest(),'flag':os.getenv('ONEIRODEX_OPERATOR_TEST_FLAG')}\n"
        "Path(os.environ['ONEIRODEX_TEST_CAPTURE']).write_text(json.dumps(result),encoding='utf-8')\n",
        encoding='utf-8',
    )
    (tmp_path / 'bin/uvicorn.cmd').write_text(
        '@echo off\npython "%~dp0capture_env.py"\n', encoding='utf-8',
    )
    env = dict(os.environ)
    env.pop('PORT', None)
    env.pop('SECRET_KEY', None)
    env['PYTHONPATH'] = str(tmp_path)
    env['ONEIRODEX_TEST_CAPTURE'] = str(capture)
    env['PATH'] = str(tmp_path / 'bin') + os.pathsep + str(Path(sys.executable).parent) + os.pathsep + env['PATH']
    run = subprocess.run(
        ['cmd', '/d', '/c', str(launcher)], cwd=tmp_path, env=env,
        capture_output=True, text=True, encoding='utf-8', timeout=30,
    )
    assert run.returncode == 0, run.stderr
    values = json.loads(capture.read_text(encoding='utf-8'))
    assert values['port'] == '6120'
    assert values['key'] == hashlib.sha256(key.encode()).hexdigest()
    assert values['flag'] == 'left=right'


@pytest.mark.skipif(not BASH or not Path(BASH).is_file(), reason='Bash required')
@pytest.mark.parametrize('mode', ['fresh', 'preserve', 'force'])
def test_linux_preserved_configuration_does_not_rotate_database_password(tmp_path, mode):
    declarations = tmp_path / 'source-declarations.sh'
    declarations.write_text((ROOT / 'install-linux.sh').read_text(encoding='utf-8'),
                            encoding='utf-8', newline='\n')
    if mode != 'fresh':
        (tmp_path / '.env').write_bytes(PRIOR)
    script = '''
source "$1"
SCRIPT_DIR="$2"
LOG_FILE="$2/install.log"
FORCE_INSTALL="$3"
SKIP_DB=false
PACKAGE_MANAGER=apt
DB_PASSWORD=synthetic-prior-password
# Intercept every privileged command; never invoke sudo, psql or systemctl.
sudo() {
    printf '%s\\n' "$*" >> "$SCRIPT_DIR/system-calls"
    if [ "$*" = '-u postgres psql' ]; then cat > "$SCRIPT_DIR/captured.sql"; fi
    return 0
}
generate_secure_password() { printf synthetic-new-password; }
configure_postgresql_auth() { :; }
test_database_connection() { return 0; }
setup_postgresql
printf '%s' "$DB_PASSWORD" > "$SCRIPT_DIR/password-after"
printf '%s' "$SKIP_DB" > "$SCRIPT_DIR/skip-database-probe"
'''
    run = subprocess.run(
        [BASH, '--noprofile', '--norc', '-c', script, 'native-config-contract',
         declarations.as_posix(), tmp_path.as_posix(), 'true' if mode == 'force' else 'false'],
        capture_output=True, text=True, encoding='utf-8', timeout=30,
    )
    assert run.returncode == 0, run.stderr
    if mode == 'preserve':
        assert not (tmp_path / 'system-calls').exists()
        assert (tmp_path / 'password-after').read_text() == 'synthetic-prior-password'
        assert (tmp_path / '.env').read_bytes() == PRIOR
        assert (tmp_path / 'skip-database-probe').read_text() == 'true'
    else:
        assert (tmp_path / 'system-calls').exists()
        assert 'ALTER USER oneirodexuser' in (tmp_path / 'captured.sql').read_text()
        assert (tmp_path / 'password-after').read_text() == 'synthetic-new-password'
        assert (tmp_path / 'skip-database-probe').read_text() == 'false'
