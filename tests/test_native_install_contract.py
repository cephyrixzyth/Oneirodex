"""Keep native installers aligned with the source-built ASGI delivery contract."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_all_native_installers_build_five_spas_with_node_22_and_validate_native_runtime():
    windows = (ROOT / 'install-windows.ps1').read_text(encoding='utf-8')
    linux = (ROOT / 'install-linux.sh').read_text(encoding='utf-8')
    macos = (ROOT / 'install-macos.sh').read_text(encoding='utf-8')

    assert "-notmatch '^22\\.'" in windows
    assert '& npm.cmd ci --no-audit --no-fund' in windows
    assert '& npm.cmd run build:native-spas' in windows
    assert "Join-Path $ScriptDir 'scripts\\validate-native-install.py'" in windows
    assert '    Test-NativeRuntime' in windows

    for installer in (linux, macos):
        assert '"$node_version" != 22.*' in installer
        assert 'npm ci --no-audit --no-fund' in installer
        assert 'npm run build:native-spas' in installer
        assert 'scripts/validate-native-install.py' in installer


def test_native_install_validator_checks_exactly_five_spa_entrypoints_without_flask_factory():
    validator = (ROOT / 'scripts' / 'validate-native-install.py').read_text(encoding='utf-8')

    for target in ('member-app', 'member-auth', 'admin-app', 'admin-pilot', 'ops-glance'):
        assert f"'{target}'" in validator
    assert 'create_app(' not in validator
    assert 'NativeRuntimeContext(' in validator
    assert 'server-ui-manifest.json' in validator
    assert 'validate_assets(args.root)' in validator


def test_native_spa_build_stages_five_outputs_and_promotes_only_after_validation():
    script = (ROOT / 'scripts' / 'build-native-spas.mjs').read_text(encoding='utf-8')

    assert "major !== 22" in script
    assert 'ONEIRODEX_NATIVE_DIST_ROOT: stageRoot' in script
    assert "'server-ui-manifest.json'" in script
    assert 'package_lock_sha256' in script
    assert 'source_commit' in script
    assert 'validateManifest()' in script
    assert 'validateManifest()\n  promoteGeneration({ current: distRoot, staged: stageRoot, backup: backupRoot })' in script
    for target in ('member-app', 'member-auth', 'admin-app', 'admin-pilot', 'ops-glance'):
        assert f"['{target}'" in script
