"""System mark prompts and paths stay catalogue-safe and slug-safe."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from oneirodex.utils.system_marks import (
    build_system_mark_prompt,
    generate_system_marks,
    list_system_marks_catalog,
    mark_path,
    platform_choices,
    platform_ids,
    static_mark_url,
    system_mark_lab_spec,
    theme_slugs,
)


def test_platform_ids_cover_library_platform_enum():
    ids = platform_ids()
    assert 'nes' in ids
    assert 'ps2' in ids
    assert len(ids) >= 70


def test_theme_slugs_include_default_and_presets():
    slugs = theme_slugs()
    assert slugs[0] == 'default'
    assert 'afterglow' in slugs
    assert 'signal' in slugs


def test_prompt_is_catalogue_only():
    prompt = build_system_mark_prompt(platform='nes', theme='afterglow')
    assert 'Nintendo Entertainment System' in prompt
    assert 'front-loading' in prompt or 'NES' in prompt
    assert 'recognizable' in prompt
    assert '#' in prompt  # accent hex from preset tokens
    for banned in ('/mnt/', 'C:\\', 'username', 'password', 'library/'):
        assert banned not in prompt


def test_mark_path_rejects_traversal(tmp_path: Path):
    with pytest.raises(ValueError):
        mark_path('../evil', 'nes', package_root=tmp_path)
    with pytest.raises(ValueError):
        mark_path('afterglow', '../nes', package_root=tmp_path)


def test_static_url_shape():
    assert static_mark_url('afterglow', 'nes') == '/static/library/system-marks/afterglow/nes.webp'


def test_catalog_lists_themes(tmp_path: Path):
    rows = list_system_marks_catalog(package_root=tmp_path)
    assert any(row['theme'] == 'default' for row in rows)
    assert all('generated' in row and 'total' in row for row in rows)


def test_generate_skips_without_ai_when_file_exists(tmp_path: Path, monkeypatch):
    monkeypatch.setenv('ENABLE_AI_ARTWORK', 'false')
    target = mark_path('default', 'nes', package_root=tmp_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b'RIFF....WEBP')
    result = generate_system_marks(
        themes=['default'],
        platforms=['nes'],
        package_root=tmp_path,
        force=False,
    )
    assert result['skipped'] == 1
    assert result['generated'] == 0
    assert result['errors'] == []
    assert 'path' not in result['results'][0]
    assert result['results'][0]['url'] == '/static/library/system-marks/default/nes.webp'


def test_cli_help_exits_zero():
    script = Path(__file__).resolve().parents[1] / 'scripts' / 'generate_system_marks.py'
    completed = subprocess.run(
        [sys.executable, str(script), '--help'],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert 'Generate AI system marks' in completed.stdout
    assert '--theme' in completed.stdout
    assert '--all' in completed.stdout


@pytest.fixture
def admin_user(db_session):
    from oneirodex.models import User

    uid = str(uuid4())
    suffix = uid[:8]
    user = User(
        user_id=uid,
        name=f'MarksAdmin_{suffix}',
        email=f'marksadmin_{suffix}@test.com',
        role='admin',
        is_email_verified=True,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


def test_art_studio_system_marks_api_catalog_and_generate(client, db_session, admin_user, tmp_path):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user.id)
        sess['_fresh'] = True

    with patch(
        'oneirodex.routes_admin_ext.art_studio.list_system_marks_catalog',
        return_value=[{
            'theme': 'default',
            'era': 'wood_den_80s',
            'generated': 0,
            'total': 72,
            'platforms': [],
            'manifest_platforms': [],
            'complete': False,
        }],
    ):
        catalog = client.get('/admin/api/art-studio/system-marks')
    assert catalog.status_code == 200
    body = catalog.get_json()
    assert body.get('ok') is True
    assert body['count'] == 1
    assert body['items'][0]['theme'] == 'default'
    assert any(row['id'] == 'nes' for row in body.get('all_platforms') or [])

    lab = client.get('/admin/api/art-studio/system-marks/lab?theme=default&platform=nes')
    assert lab.status_code == 200
    lab_body = lab.get_json()
    assert lab_body.get('ok') is True
    assert 'NES' in lab_body['prompt'] or 'Nintendo' in lab_body['prompt']
    assert lab_body['url'] == '/static/library/system-marks/default/nes.webp'
    assert 'path' not in lab_body

    with patch(
        'oneirodex.routes_admin_ext.art_studio.generate_system_marks',
        return_value={'generated': 1, 'skipped': 0, 'errors': [], 'results': []},
    ) as gen:
        response = client.post(
            '/admin/api/art-studio/system-marks/generate',
            json={'themes': ['default'], 'platforms': ['nes'], 'force': False},
        )
    assert response.status_code == 201
    payload = response.get_json()
    assert payload.get('ok') is True
    assert payload['generated'] == 1
    gen.assert_called_once()
    assert gen.call_args.kwargs['themes'] == ['default']
    assert gen.call_args.kwargs['platforms'] == ['nes']
    assert gen.call_args.kwargs.get('prompt') is None


def test_art_studio_lab_prompt_requires_one_pair(client, db_session, admin_user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(admin_user.id)
        sess['_fresh'] = True

    rejected = client.post(
        '/admin/api/art-studio/system-marks/generate',
        json={'themes': ['default'], 'prompt': 'custom NES mark'},
    )
    assert rejected.status_code == 400
    assert rejected.get_json().get('error_code') == 'bad_request'

    with patch(
        'oneirodex.routes_admin_ext.art_studio.generate_system_marks',
        return_value={'generated': 1, 'skipped': 0, 'errors': [], 'results': []},
    ) as gen:
        ok = client.post(
            '/admin/api/art-studio/system-marks/generate',
            json={
                'themes': ['default'],
                'platforms': ['nes'],
                'force': True,
                'prompt': 'custom NES mark',
            },
        )
    assert ok.status_code == 201
    assert gen.call_args.kwargs['prompt'] == 'custom NES mark'
    assert gen.call_args.kwargs['force'] is True


def test_lab_spec_is_catalogue_only(tmp_path: Path):
    spec = system_mark_lab_spec(theme='afterglow', platform='nes', package_root=tmp_path)
    assert spec['theme'] == 'afterglow'
    assert spec['platform'] == 'nes'
    assert spec['exists'] is False
    assert 'Nintendo' in spec['prompt']
    for banned in ('/mnt/', 'C:\\', 'username', 'password'):
        assert banned not in spec['prompt']
    assert spec['url'] == '/static/library/system-marks/afterglow/nes.webp'
    assert 'path' not in spec


def test_platform_choices_cover_enum():
    choices = platform_choices()
    ids = {row['id'] for row in choices}
    assert 'nes' in ids
    assert any(row['label'] for row in choices if row['id'] == 'nes')
