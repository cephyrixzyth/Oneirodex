"""Exercise actual POSIX configuration/launcher boundaries with inert app commands."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from dotenv import dotenv_values
import pytest


ROOT = Path(__file__).resolve().parents[1]
BASH = 'C:/Program Files/Git/bin/bash.exe' if os.name == 'nt' else shutil.which('bash')
pytestmark = pytest.mark.skipif(not BASH or not Path(BASH).is_file(), reason='Bash required')
KEYS = ['DATA_FOLDER_GAMES', 'ONEIRODEX_LIBRARY_ROOTS', 'SECRET_KEY', 'PORT',
        'BASE_FOLDER_POSIX', 'BASE_FOLDER_WINDOWS', 'ONEIRODEX_TEST_FLAG',
        'FIRST', 'SECOND', 'EMPTY']


@pytest.fixture
def launcher_stage(tmp_path):
    if os.name == 'nt':
        pytest.skip('POSIX exec requires Unix; Windows uses startweb_windows.cmd')
    subprocess.run([sys.executable, '-m', 'venv', '--without-pip', str(tmp_path / 'venv')],
                   check=True, capture_output=True, timeout=30)
    activate = tmp_path / 'venv/bin/activate'
    activate.write_text(activate.read_text(encoding='utf-8') +
                        '\nexport ONEIRODEX_TEST_ACTIVATIONS=$((${ONEIRODEX_TEST_ACTIVATIONS:-0}+1))\n',
                        encoding='utf-8')
    (tmp_path / 'bin').mkdir()
    (tmp_path / 'scripts').mkdir()
    (tmp_path / 'startweb.sh').write_text(
        (ROOT / 'startweb.sh').read_text(encoding='utf-8'), encoding='utf-8', newline='\n',
    )
    helper = ROOT / 'scripts/run_with_dotenv.py'
    if helper.exists():
        shutil.copyfile(helper, tmp_path / 'scripts/run_with_dotenv.py')
    # Every real application entry is intercepted, before any app/DB imports.
    python_shim = tmp_path / 'bin/python3'
    python_shim.write_text('''#!/bin/bash
if [ "$1" = '-m' ] && [ "$2" = scripts.startup_art ]; then
    printf 'splash\\n' >> "$ONEIRODEX_TEST_EVENTS"
    exit 0
fi
if [ "$1" = '-c' ]; then
    if [[ "$2" == *oneirodex.init_manager* ]]; then
        printf 'init-or-epilogue\\n' >> "$ONEIRODEX_TEST_EVENTS"
        exit 0
    fi
    if [[ "$2" == *reset_setup_state* ]]; then
        printf 'reset\\n' >> "$ONEIRODEX_TEST_EVENTS"
        exit 0
    fi
fi
exec "$ONEIRODEX_TEST_REAL_PYTHON" "$@"
''', encoding='utf-8', newline='\n')
    python_shim.chmod(0o700)
    # Replace only the owned venv symlink, never its external interpreter target.
    venv_python = tmp_path / 'venv/bin/python3'
    venv_python.unlink()
    venv_python.write_bytes(python_shim.read_bytes())
    venv_python.chmod(0o700)
    capture = tmp_path / 'capture_env.py'
    capture.write_text(
        'import os,sys,json\nfrom pathlib import Path\n'
        f'keys={KEYS!r}\n'
        "Path('capture.json').write_text(json.dumps({'values':{k:os.environ.get(k) for k in keys},'args':sys.argv[1:],'parent_pid':os.getppid(),'expected_parent_pid':int(os.environ['ONEIRODEX_TEST_LAUNCH_PID']),'activation_count':int(os.environ.get('ONEIRODEX_TEST_ACTIVATIONS','0')),'loader_marker':os.environ.get('ONEIRODEX_NATIVE_DOTENV_READY')}),encoding='utf-8')\n",
        encoding='utf-8',
    )
    uvicorn = tmp_path / 'bin/uvicorn'
    uvicorn.write_text(
        '#!/bin/bash\nexec "$ONEIRODEX_TEST_REAL_PYTHON" "$ONEIRODEX_TEST_CAPTURE_SCRIPT" "$@"\n',
        encoding='utf-8', newline='\n',
    )
    uvicorn.chmod(0o700)
    return tmp_path


def run_launcher(stage, *, inherited=None, args=(), from_parent=False):
    env = dict(os.environ)
    for key in [*KEYS, 'UVICORN_WORKERS', 'ONEIRODEX_NATIVE_DOTENV_READY', 'ONEIRODEX_TEST_ACTIVATIONS']:
        env.pop(key, None)
    env.update(inherited or {})
    env['PATH'] = (stage / 'bin').as_posix() + os.pathsep + str(Path(BASH).parent) + os.pathsep + env['PATH']
    if os.name == 'nt':
        # Git Bash otherwise rewrites '/' when handing env to native Python.
        env['MSYS2_ENV_CONV_EXCL'] = 'BASE_FOLDER_POSIX;BASE_FOLDER_WINDOWS'
    env['ONEIRODEX_TEST_REAL_PYTHON'] = Path(sys.executable).as_posix()
    env['ONEIRODEX_TEST_CAPTURE_SCRIPT'] = (stage / 'capture_env.py').as_posix()
    env['ONEIRODEX_TEST_EVENTS'] = (stage / 'events').as_posix()
    cwd = stage.parent if from_parent else stage
    script = (stage.name + '/startweb.sh') if from_parent else (stage / 'startweb.sh').as_posix()
    return subprocess.run(
        [BASH, '--noprofile', '--norc', '-c',
         'export ONEIRODEX_TEST_LAUNCH_PID=$$; exec "$@"', 'owned-native-launch',
         BASH, '--noprofile', '--norc', script, *args],
        cwd=cwd, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30,
    )


@pytest.mark.parametrize('installer', ['install-linux.sh', 'install-macos.sh'])
@pytest.mark.parametrize('complex_paths', [False, True])
def test_posix_installer_values_survive_actual_launcher(launcher_stage, installer, complex_paths):
    stage = launcher_stage
    source = (ROOT / installer).read_text(encoding='utf-8')
    if installer == 'install-macos.sh':
        assert source.rstrip().endswith('main "$@"')
        source = source.rstrip()[:-len('main "$@"')]
    declarations = stage / 'declarations.sh'
    declarations.write_text(source, encoding='utf-8', newline='\n')
    games = stage / ('Game Library' if complex_paths else 'games')
    games.mkdir()
    roots = ('Family Library=' + games.as_posix() + '|Archive=' + (stage / 'archive').as_posix()
             if complex_paths else 'Family=' + games.as_posix())
    env = dict(os.environ, TEST_ROOT=stage.as_posix(), TEST_GAMES=games.as_posix(), TEST_ROOTS=roots)
    script = '''source "$1"
SCRIPT_DIR="$TEST_ROOT"; LOG_FILE="$TEST_ROOT/install.log"
GAMES_DIR="$TEST_GAMES"; LIBRARY_ROOTS="$TEST_ROOTS"
DB_PASSWORD=synthetic-test-only; DB_USER=review
DB_NAME=oneirodex_launch_test; TEST_DB_NAME=oneirodex_launch_tests
CUSTOM_PORT=6120; FORCE_INSTALL=false; DEV_MODE=false
configure_application
'''
    writer = subprocess.run(
        [BASH, '--noprofile', '--norc', '-c', script, 'native-config-contract', declarations.as_posix()],
        env=env, capture_output=True, text=True, encoding='utf-8', timeout=30,
    )
    assert writer.returncode == 0, writer.stderr
    prior = (stage / '.env').read_bytes()
    expected = dotenv_values(stage / '.env')
    assert expected['DATA_FOLDER_GAMES'] == games.as_posix()
    assert expected['ONEIRODEX_LIBRARY_ROOTS'] == roots
    run = run_launcher(stage)
    assert run.returncode == 0, run.stderr
    result = json.loads((stage / 'capture.json').read_text(encoding='utf-8'))
    for key in ['DATA_FOLDER_GAMES', 'ONEIRODEX_LIBRARY_ROOTS', 'PORT', 'BASE_FOLDER_POSIX']:
        assert result['values'][key] == expected[key], key
    assert hashlib.sha256(result['values']['SECRET_KEY'].encode()).digest() == hashlib.sha256(expected['SECRET_KEY'].encode()).digest()
    assert (stage / '.env').read_bytes() == prior
    assert result['parent_pid'] == result['expected_parent_pid']
    assert (stage / 'events').read_text(encoding='utf-8').splitlines().count('splash') == 1


def test_dotenv_is_data_and_does_not_execute_shell_substitution(launcher_stage):
    stage = launcher_stage
    literal = '$(printf marker > injected-marker)'
    (stage / '.env').write_text('ONEIRODEX_TEST_FLAG=' + literal + '\n', encoding='utf-8')
    run = run_launcher(stage)
    assert run.returncode == 0, run.stderr
    assert not (stage / 'injected-marker').exists()
    result = json.loads((stage / 'capture.json').read_text(encoding='utf-8'))
    assert result['values']['ONEIRODEX_TEST_FLAG'] == literal


def test_retained_dotenv_quotes_interpolation_empty_and_parent_precedence(launcher_stage):
    stage = launcher_stage
    prior = b"FIRST='alpha beta'\nSECOND=${FIRST}-tail\nEMPTY=\nPORT=6120\nONEIRODEX_TEST_FLAG='left=right'\n"
    (stage / '.env').write_bytes(prior)
    run = run_launcher(stage, inherited={'FIRST': 'parent', 'PORT': '5006', 'EMPTY': 'parent'})
    assert run.returncode == 0, run.stderr
    values = json.loads((stage / 'capture.json').read_text(encoding='utf-8'))['values']
    assert values['FIRST'] == 'alpha beta'
    assert values['SECOND'] == 'alpha beta-tail'
    assert values['EMPTY'] == ''
    assert values['PORT'] == '6120'
    assert values['ONEIRODEX_TEST_FLAG'] == 'left=right'
    assert (stage / '.env').read_bytes() == prior


@pytest.mark.parametrize('invalid', [
    b'1INVALID=synthetic-hidden-canary\n',
    b'ONEIRODEX_TEST_FLAG=synthetic-hidden-canary\x00tail\n',
    b'ONEIRODEX_TEST_FLAG=synthetic-hidden-canary\xff\n',
    b'ONEIRODEX_TEST_FLAG="synthetic-hidden-canary\n',
])
def test_invalid_dotenv_stops_before_any_app_startup(launcher_stage, invalid):
    stage = launcher_stage
    (stage / '.env').write_bytes(invalid)
    run = run_launcher(stage)
    assert run.returncode != 0
    assert not (stage / 'events').exists()
    assert not (stage / 'capture.json').exists()
    assert (stage / '.env').read_bytes() == invalid
    assert 'synthetic-hidden-canary' not in run.stdout + run.stderr


def test_launcher_without_dotenv_keeps_inherited_port(launcher_stage):
    run = run_launcher(launcher_stage, inherited={'PORT': '6121'})
    assert run.returncode == 0, run.stderr
    result = json.loads((launcher_stage / 'capture.json').read_text(encoding='utf-8'))
    assert result['values']['PORT'] == '6121'
    assert '--port' in result['args'] and '6121' in result['args']


def test_launcher_relative_path_from_parent_preserves_config_and_pid(launcher_stage):
    (launcher_stage / '.env').write_text('PORT=6120\n', encoding='utf-8')
    run = run_launcher(launcher_stage, from_parent=True)
    assert run.returncode == 0, run.stderr
    result = json.loads((launcher_stage / 'capture.json').read_text(encoding='utf-8'))
    assert result['values']['PORT'] == '6120'
    assert result['parent_pid'] == result['expected_parent_pid']


def test_virtualenv_activation_is_not_repeated_on_reentry(launcher_stage):
    (launcher_stage / '.env').write_text('PORT=6120\n', encoding='utf-8')
    run = run_launcher(launcher_stage)
    assert run.returncode == 0, run.stderr
    result = json.loads((launcher_stage / 'capture.json').read_text(encoding='utf-8'))
    assert result['activation_count'] == 1
    assert result['loader_marker'] is None


def test_stale_parent_loader_marker_does_not_skip_configuration(launcher_stage):
    (launcher_stage / '.env').write_text('PORT=6120\n', encoding='utf-8')
    run = run_launcher(launcher_stage, inherited={'ONEIRODEX_NATIVE_DOTENV_READY': '1', 'PORT': '5006'})
    assert run.returncode == 0, run.stderr
    result = json.loads((launcher_stage / 'capture.json').read_text(encoding='utf-8'))
    assert result['values']['PORT'] == '6120'
    assert result['activation_count'] == 1


def test_force_setup_argument_survives_env_loading_without_real_reset(launcher_stage):
    (launcher_stage / '.env').write_text('PORT=6120\n', encoding='utf-8')
    run = run_launcher(launcher_stage, args=('--force-setup',))
    assert run.returncode == 0, run.stderr
    assert 'reset' in (launcher_stage / 'events').read_text(encoding='utf-8').splitlines()
    assert not (launcher_stage / 'capture.json').exists()


@pytest.mark.parametrize('name', ['BASH_ENV', 'SHELLOPTS', 'BASHOPTS'])
def test_dotenv_cannot_enable_shell_startup_hooks(launcher_stage, name):
    hook = launcher_stage / 'controlled-hook.sh'
    hook.write_text('printf marker > shell-startup-marker\n', encoding='utf-8')
    value = hook.as_posix() if name == 'BASH_ENV' else 'xtrace'
    (launcher_stage / '.env').write_text(name + '=' + value + '\n', encoding='utf-8')
    run = run_launcher(launcher_stage)
    assert not (launcher_stage / 'shell-startup-marker').exists()
    assert run.returncode != 0
    assert not (launcher_stage / 'events').exists()
    assert not (launcher_stage / 'capture.json').exists()


def test_missing_virtualenv_stops_before_startup(launcher_stage):
    (launcher_stage / 'venv/bin/activate').unlink()
    run = run_launcher(launcher_stage)
    assert run.returncode != 0
    assert not (launcher_stage / 'events').exists()
    assert not (launcher_stage / 'capture.json').exists()


@pytest.fixture
def environment_loader():
    spec = importlib.util.spec_from_file_location('native_dotenv_loader', ROOT / 'scripts/run_with_dotenv.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_loader_exec_failure_is_generic_and_preserves_arguments(environment_loader, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / '.env').write_text(
        'ONEIRODEX_TEST_FLAG=synthetic-hidden-canary\nONEIRODEX_NATIVE_DOTENV_READY=0\n', encoding='utf-8',
    )
    observed = {}

    def fail_exec(executable, argv, environment):
        observed.update(executable=executable, argv=argv,
                        value=environment.get('ONEIRODEX_TEST_FLAG'),
                        ready=environment.get('ONEIRODEX_NATIVE_DOTENV_READY'))
        raise OSError('synthetic-hidden-canary /private-path')

    monkeypatch.setattr(environment_loader.os, 'execvpe', fail_exec)
    assert environment_loader.main(['./startweb.sh', '--force-setup']) == 1
    assert observed['executable'] == 'bash'
    assert observed['argv'] == ['bash', './startweb.sh', '--force-setup']
    assert observed['value'] == 'synthetic-hidden-canary'
    assert observed['ready'] == str(os.getpid())
    output = capsys.readouterr()
    assert 'synthetic-hidden-canary' not in output.out + output.err
    assert '/private-path' not in output.out + output.err


@pytest.mark.parametrize('failure', ['missing_file', 'missing_dependency'])
def test_loader_failure_never_executes(environment_loader, tmp_path, monkeypatch, capsys, failure):
    monkeypatch.chdir(tmp_path)
    if failure == 'missing_dependency':
        (tmp_path / '.env').write_text('PORT=6120\n', encoding='utf-8')
        monkeypatch.setitem(sys.modules, 'dotenv', None)
    monkeypatch.setattr(environment_loader.os, 'execvpe', lambda *args: pytest.fail('Loader must not exec'))
    assert environment_loader.main(['./startweb.sh']) == 1
    assert 'Unable to load native configuration' in capsys.readouterr().err


def test_loader_requires_launcher_without_executing(environment_loader, monkeypatch):
    monkeypatch.setattr(environment_loader.os, 'execvpe', lambda *args: pytest.fail('Loader must not exec'))
    assert environment_loader.main([]) == 2
