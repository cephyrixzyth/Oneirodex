"""Checks for the framework-neutral icon catalog and generated React adapter."""

from copy import deepcopy
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.generate_icon_adapters import load_manifest, validate_manifest

ROOT = Path(__file__).resolve().parents[1]


def test_shared_catalog_has_accessibility_guidance_for_each_icon():
    manifest = load_manifest()
    assert all(icon['accessible_use'] for icon in manifest['icons'].values())


def test_generated_react_adapter_is_current():
    result = subprocess.run(
        [sys.executable, str(ROOT / 'scripts' / 'generate_icon_adapters.py'), '--check'],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_manifest_rejects_unsafe_shapes_and_duplicate_aliases():
    manifest = load_manifest()
    bad_tag = deepcopy(manifest)
    bad_tag['icons']['ownership']['shapes'][0]['tag'] = 'script'
    with pytest.raises(ValueError, match='unsupported SVG tag'):
        validate_manifest(bad_tag)

    duplicate_alias = deepcopy(manifest)
    duplicate_alias['icons']['ownership']['aliases'] = ['store', 'store']
    with pytest.raises(ValueError, match='duplicate alias/canonical key'):
        validate_manifest(duplicate_alias)


def test_spas_use_generated_shared_icons_without_template_adapters():
    generated = (ROOT / 'frontend' / 'shared' / 'src' / 'generatedIconPaths.tsx').read_text(encoding='utf-8')
    renderer = (ROOT / 'frontend' / 'shared' / 'src' / 'railIcons.tsx').read_text(encoding='utf-8')
    assert 'sharedIconPaths' in generated
    assert 'sharedIconPaths' in renderer
    templates = ROOT / 'oneirodex' / 'templates'
    assert not templates.exists() or not list(templates.rglob('*.html'))
