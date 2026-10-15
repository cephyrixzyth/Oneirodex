from __future__ import annotations

from io import BytesIO
from uuid import uuid4

from PIL import Image

from oneirodex.models import Library, User
from oneirodex.platform import LibraryPlatform


def _admin(db_session):
    suffix = uuid4().hex[:10]
    user = User(
        user_id=str(uuid4()),
        name=f'CreateLibrary_{suffix}',
        email=f'create-library-{suffix}@test.com',
        role='admin',
        is_email_verified=True,
    )
    user.set_password('testpass123')
    db_session.add(user)
    db_session.commit()
    return user


def _login(client, user):
    with client.session_transaction() as session:
        session['_user_id'] = str(user.id)
        session['_fresh'] = True


def test_admin_create_library_api_preserves_watch_depth_and_normalizes_image(
    client, db_session, tmp_path
):
    admin = _admin(db_session)
    _login(client, admin)
    client.application.config['UPLOAD_FOLDER'] = str(tmp_path)
    image_bytes = BytesIO()
    Image.new('RGB', (1200, 600), color=(40, 90, 50)).save(image_bytes, format='JPEG')
    image_bytes.seek(0)

    response = client.post(
        '/api/admin/libraries',
        data={
            'name': 'API Created Library',
            'platform': 'NES',
            'scan_depth': '2',
            'watch_enabled': 'off',
            'image': (image_bytes, 'cover.jpg'),
        },
        content_type='multipart/form-data',
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body['ok'] is True
    library = db_session.get(Library, body['library_uuid'])
    assert library is not None
    assert library.name == 'API Created Library'
    assert library.platform == LibraryPlatform.NES
    assert library.scan_depth == 2
    assert library.watch_enabled is False
    assert library.image_url.startswith('/static/library/images/')
    image_path = tmp_path / 'images' / library.image_url.rsplit('/', 1)[-1]
    with Image.open(image_path) as saved:
        assert saved.format == 'PNG'
        assert saved.size == (1024, 512)


def test_admin_create_library_api_rejects_invalid_watch_setting(client, db_session):
    admin = _admin(db_session)
    _login(client, admin)

    response = client.post(
        '/api/admin/libraries',
        json={
            'name': 'Rejected Library',
            'platform': 'NES',
            'scan_depth': 1,
            'watch_enabled': 'sometimes',
        },
    )

    assert response.status_code == 400
    assert response.get_json()['error_code'] == 'bad_request'
    assert db_session.query(Library).filter_by(name='Rejected Library').count() == 0


def test_admin_library_editor_reads_and_updates_full_fields(client, db_session, tmp_path):
    admin = _admin(db_session)
    _login(client, admin)
    client.application.config['UPLOAD_FOLDER'] = str(tmp_path)
    library = Library(
        uuid=str(uuid4()), name='Before edit', platform=LibraryPlatform.NES,
        scan_depth=1, watch_enabled=None, image_url='/static/old.png',
    )
    db_session.add(library)
    db_session.commit()

    loaded = client.get(f'/api/admin/libraries/{library.uuid}')
    assert loaded.status_code == 200
    assert loaded.get_json() == {
        'uuid': library.uuid,
        'name': 'Before edit',
        'platform': 'NES',
        'scan_depth': 1,
        'last_scan_folder': None,
        'group_name': None,
        'image_url': '/static/old.png',
        'watch_enabled': None,
        'watch_effective': False,
        'watch_global_enabled': False,
        'ok': True,
        'error': None,
        'error_code': None,
        'success': True,
    }

    image_bytes = BytesIO()
    Image.new('RGB', (24, 24), color=(30, 80, 40)).save(image_bytes, format='PNG')
    image_bytes.seek(0)
    updated = client.put(
        f'/api/admin/libraries/{library.uuid}',
        data={
            'name': 'After edit', 'platform': 'SNES', 'scan_depth': '2',
            'watch_enabled': 'off', 'image': (image_bytes, 'cover.png'),
        },
        content_type='multipart/form-data',
    )
    assert updated.status_code == 200
    body = updated.get_json()
    assert body['name'] == 'After edit'
    assert body['platform'] == 'SNES'
    assert body['scan_depth'] == 2
    assert body['watch_enabled'] is False
    assert body['image_url'].startswith('/static/library/images/')
    assert db_session.get(Library, library.uuid).name == 'After edit'
    assert (tmp_path / 'images' / body['image_url'].rsplit('/', 1)[-1]).is_file()


def test_admin_library_editor_rejects_bad_fields_and_missing_library(client, db_session):
    admin = _admin(db_session)
    _login(client, admin)
    library = Library(uuid=str(uuid4()), name='Keep', platform=LibraryPlatform.NES)
    db_session.add(library)
    db_session.commit()

    bad = client.put(f'/api/admin/libraries/{library.uuid}', json={
        'name': 'Changed', 'platform': 'not-a-platform', 'scan_depth': 9,
    })
    assert bad.status_code == 400
    assert db_session.get(Library, library.uuid).name == 'Keep'
    assert client.get('/api/admin/libraries/missing').status_code == 404

