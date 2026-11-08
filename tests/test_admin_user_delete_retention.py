import hashlib
import time
from uuid import uuid4
from pathlib import Path

from oneirodex.models import (
    DownloadRequest,
    DuplicateFixLog,
    Game,
    ChatChannel,
    ChatMessageAttachment,
    EmulatorSave,
    EmulatorSaveGeneration,
    InviteToken,
    Library,
    Newsletter,
    SystemEvents,
    User,
    UserDeletionFileJob,
    UserAttractModeSettings,
    user_favorites,
    user_game_status,
)
from oneirodex.platform import LibraryPlatform


def _make_user(name: str, role: str) -> User:
    user = User(
        name=name,
        email=f'{name}@example.com',
        password_hash='placeholder',
        role=role,
        user_id=str(uuid4()),
        state=True,
    )
    user.set_password('a long enough test password')
    return user


def test_admin_deletion_removes_user_and_retains_anonymized_audit_event(client, db_session):
    suffix = str(uuid4())[:8]
    admin = _make_user(f'del_admin_{suffix}', 'admin')
    victim = _make_user(f'del_member_{suffix}', 'user')
    db_session.add_all([admin, victim])
    db_session.flush()
    victim_id = victim.id
    victim_name = victim.name
    victim_email = victim.email
    audit = SystemEvents(
        event_type='audit',
        event_text=(
            f'{victim_name} ({victim_email}) changed account settings at '
            r'C:\Users\private\report.txt and /srv/private/library/game.nes '
            r'and \\fileserver\share\private.log'
        ),
        event_level='information',
        audit_user=victim_id,
    )
    newsletter = Newsletter(
        subject='Account-owned announcement',
        content='Test content authored by account being deleted.',
        sender_id=victim_id,
    )
    db_session.add_all([audit, newsletter])
    db_session.commit()
    newsletter_id = newsletter.id

    with client.session_transaction() as session:
        session['_user_id'] = str(admin.id)
        session['_fresh'] = True

    response = client.delete(f'/admin/api/user/{victim_id}')

    assert response.status_code == 200, response.get_data(as_text=True)
    assert db_session.get(User, victim_id) is None
    assert db_session.get(Newsletter, newsletter_id) is None
    retained = db_session.get(SystemEvents, audit.id)
    assert retained is not None
    assert retained.audit_user is None
    assert victim_name not in retained.event_text
    assert victim_email not in retained.event_text
    assert r'C:\Users\private\report.txt' not in retained.event_text
    assert '/srv/private/library/game.nes' not in retained.event_text
    assert r'\\fileserver\share\private.log' not in retained.event_text
    assert retained.event_text.count('[redacted path]') == 3


def test_native_admin_deletion_removes_rows_and_retries_owned_file_cleanup(
    db_session, tmp_path, monkeypatch,
):
    from oneirodex.runtime_native.admin_user_mutations import AdminUserMutationData
    from oneirodex.utils import user_deletion
    from oneirodex.utils.avatar import AVATAR_URL_PREFIX

    suffix = str(uuid4())[:8]
    admin = _make_user(f'native_del_admin_{suffix}', 'admin')
    victim = _make_user(f'native_del_member_{suffix}', 'user')
    upload_root = tmp_path / 'uploads'
    save_root = tmp_path / 'saves'
    save_root.mkdir()
    monkeypatch.setattr(
        user_deletion, '_storage_roots', lambda: (upload_root.resolve(), save_root.resolve()),
    )
    library = Library(
        name=f'Native deletion {suffix}',
        platform=LibraryPlatform.NES,
        display_order=1,
    )
    db_session.add_all([admin, victim, library])
    db_session.flush()
    game = Game(
        uuid=str(uuid4()),
        name=f'Native deletion game {suffix}',
        library_uuid=library.uuid,
        full_disk_path=f'/test/native-delete/{suffix}.nes',
    )
    avatar_name = f'{uuid4().hex}.png'
    victim.avatarpath = AVATAR_URL_PREFIX + avatar_name
    avatar_file = upload_root / 'images' / 'avatars_users' / avatar_name
    avatar_file.parent.mkdir(parents=True)
    avatar_file.write_bytes(b'avatar')
    avatar_thumbnail = avatar_file.with_name(f'{avatar_file.stem}_thumbnail{avatar_file.suffix}')
    avatar_thumbnail.write_bytes(b'thumbnail')
    channel = ChatChannel(name=f'deletion-{suffix}', kind='channel')
    db_session.add(game)
    db_session.add(channel)
    db_session.flush()
    victim_id, admin_id = victim.id, admin.id
    victim_name, victim_email = victim.name, victim.email
    request = DownloadRequest(
        user_id=victim_id,
        game_uuid=game.uuid,
        status='pending',
    )
    victim_invite = InviteToken(
        token=f'created-{suffix}', creator_user_id=victim.user_id,
    )
    used_invite = InviteToken(
        token=f'used-{suffix}', creator_user_id=admin.user_id,
        used=True, used_by=victim.user_id,
    )
    attract_settings = UserAttractModeSettings(
        user_id=victim.user_id, has_customized=True,
        filter_settings={}, autoplay_settings={},
    )
    duplicate_log = DuplicateFixLog(
        folder_path=f'/synthetic/{suffix}', action='keep', actor_user_id=victim_id,
    )
    prior_audit = SystemEvents(
        event_type='audit',
        event_text=f'{victim_name} at {victim_email} changed account settings',
        event_level='information',
        audit_user=victim_id,
    )
    attachment_name = f'{uuid4().hex}.png'
    attachment_file = upload_root / 'chat-attachments' / attachment_name
    attachment_file.parent.mkdir(parents=True)
    attachment_file.write_bytes(b'attachment')
    attachment = ChatMessageAttachment(
        channel_id=channel.id,
        uploaded_by_user_id=victim_id,
        file_name=attachment_name,
        original_name='private.png',
        mime='image/png',
        size_bytes=10,
    )
    owned_save_path = save_root / f'owned-{suffix}.save'
    owned_history_path = save_root / f'history-{suffix}.save'
    shared_save_path = save_root / f'shared-{suffix}.save'
    for path in (owned_save_path, owned_history_path, shared_save_path):
        path.write_bytes(b'save')
    owned_save = EmulatorSave(
        user_id=victim_id,
        game_uuid=game.uuid,
        slot_name='slot1',
        filename='slot1.state',
        size_bytes=4,
        storage_path=str(owned_save_path),
    )
    victim_shared_save = EmulatorSave(
        user_id=victim_id,
        game_uuid=game.uuid,
        slot_name='shared-copy',
        filename='shared-copy.state',
        size_bytes=4,
        storage_path=str(shared_save_path),
    )
    shared_save = EmulatorSave(
        user_id=admin_id,
        game_uuid=game.uuid,
        slot_name='shared',
        filename='shared.state',
        size_bytes=4,
        storage_path=str(shared_save_path),
    )
    db_session.add_all([
        request, victim_invite, used_invite, attract_settings,
        duplicate_log, prior_audit, attachment, owned_save,
        victim_shared_save, shared_save,
    ])
    db_session.flush()
    generation = EmulatorSaveGeneration(
        save_id=owned_save.id,
        filename=owned_save.filename,
        size_bytes=4,
        storage_path=str(owned_history_path),
    )
    db_session.add(generation)
    db_session.flush()
    db_session.execute(user_favorites.insert().values(user_id=victim_id, game_uuid=game.uuid))
    db_session.execute(user_game_status.insert().values(
        user_id=victim_id, game_uuid=game.uuid, status='beaten',
    ))
    db_session.commit()
    request_id, game_uuid = request.id, game.uuid
    attachment_id, owned_save_id = attachment.id, owned_save.id
    victim_invite_id, used_invite_id = victim_invite.id, used_invite.id
    attract_id, duplicate_id, prior_audit_id = (
        attract_settings.id, duplicate_log.id, prior_audit.id,
    )

    original_unlink = Path.unlink
    failed_once = {'path': avatar_file.resolve()}

    def fail_avatar_once(path, *args, **kwargs):
        if path.resolve() == failed_once['path']:
            failed_once['path'] = None
            raise PermissionError('synthetic failure')
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'unlink', fail_avatar_once)
    payload, error = AdminUserMutationData().delete(victim_id, admin_id)

    assert payload == {'cleanup_pending': True}
    assert error is None
    assert db_session.get(User, victim_id) is None
    assert db_session.get(DownloadRequest, request_id) is None
    assert db_session.query(Game).filter_by(uuid=game_uuid).one_or_none() is not None
    assert db_session.get(InviteToken, victim_invite_id) is None
    surviving_invite = db_session.get(InviteToken, used_invite_id)
    assert surviving_invite is not None and surviving_invite.used_by is None
    assert db_session.get(UserAttractModeSettings, attract_id) is None
    assert db_session.get(ChatMessageAttachment, attachment_id) is None
    assert db_session.get(EmulatorSave, owned_save_id) is None
    retained_duplicate = db_session.get(DuplicateFixLog, duplicate_id)
    assert retained_duplicate is not None and retained_duplicate.actor_user_id is None
    assert db_session.execute(user_favorites.select().where(
        user_favorites.c.user_id == victim_id,
    )).first() is None
    assert db_session.execute(user_game_status.select().where(
        user_game_status.c.user_id == victim_id,
    )).first() is None
    retained_prior_audit = db_session.get(SystemEvents, prior_audit_id)
    assert retained_prior_audit.audit_user is None
    assert victim_name not in retained_prior_audit.event_text
    assert victim_email not in retained_prior_audit.event_text
    deletion_event = db_session.query(SystemEvents).filter_by(
        audit_user=admin_id, event_type='audit',
    ).order_by(SystemEvents.id.desc()).first()
    assert deletion_event is not None
    assert deletion_event.event_text == 'Admin account deleted user account'
    assert victim_name not in deletion_event.event_text
    assert victim_email not in deletion_event.event_text
    assert avatar_file.exists() and not avatar_thumbnail.exists()
    assert not attachment_file.exists()
    assert not owned_save_path.exists() and not owned_history_path.exists()
    assert shared_save_path.exists()
    pending_jobs = db_session.query(UserDeletionFileJob).all()
    assert len(pending_jobs) == 1
    assert pending_jobs[0].state == 'failed'
    assert pending_jobs[0].last_error_code == 'PermissionError'

    monkeypatch.setattr(Path, 'unlink', original_unlink)
    outside_file = tmp_path / 'outside.txt'
    outside_file.write_bytes(b'outside managed root')
    db_session.add(UserDeletionFileJob(
        path_key='unsafe-path-test',
        root_path=str(upload_root.resolve()),
        relative_path='../outside.txt',
    ))
    db_session.commit()
    assert user_deletion.process_pending_file_jobs(db_session) == 1
    assert not avatar_file.exists() and not avatar_thumbnail.exists()
    assert outside_file.exists()
    unsafe_job = db_session.query(UserDeletionFileJob).one()
    assert unsafe_job.state == 'failed'
    assert unsafe_job.last_error_code == 'unsafe_path'


def test_cleanup_worker_startup_retries_a_committed_file_job(app, no_savepoint_db, tmp_path):
    from oneirodex.utils.user_deletion import start_file_cleanup_worker

    relative_path = 'queued/deleted-after-restart.bin'
    target = tmp_path / relative_path
    target.parent.mkdir(parents=True)
    target.write_bytes(b'owned file')
    root = str(tmp_path.resolve())
    job = UserDeletionFileJob(
        path_key=hashlib.sha256(f'{root}\0{relative_path}'.encode('utf-8')).hexdigest(),
        root_path=root,
        relative_path=relative_path,
        state='failed',
        attempts=1,
        last_error_code='PermissionError',
    )
    no_savepoint_db.add(job)
    no_savepoint_db.commit()

    worker = start_file_cleanup_worker(app, interval_seconds=0.02)
    assert worker is not None
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and target.exists():
            time.sleep(0.01)
    finally:
        worker.stop()
        worker.thread.join(timeout=5)

    no_savepoint_db.expire_all()
    assert not target.exists()
    assert no_savepoint_db.query(UserDeletionFileJob).filter_by(
        root_path=root, relative_path=relative_path,
    ).one_or_none() is None


def test_avatar_replacement_queues_old_bytes_before_pointer_commit_and_retries(db_session, tmp_path):
    from io import BytesIO
    import logging
    from PIL import Image
    from werkzeug.datastructures import FileStorage
    from oneirodex.utils.avatar import AVATAR_URL_PREFIX
    from oneirodex.utils.avatar import save_avatar
    from oneirodex.utils.user_deletion import (
        enqueue_avatar_replacement_cleanup,
        process_pending_file_jobs,
    )

    user = _make_user(f'avatar_replace_{str(uuid4())[:8]}', 'user')
    old_name = f'{uuid4().hex}.png'
    user.avatarpath = AVATAR_URL_PREFIX + old_name
    db_session.add(user)
    db_session.commit()
    avatar_dir = tmp_path / 'images' / 'avatars_users'
    avatar_dir.mkdir(parents=True)
    old_file = avatar_dir / old_name
    old_thumbnail = avatar_dir / f'{Path(old_name).stem}_thumbnail.png'
    old_file.write_bytes(b'old avatar')
    old_thumbnail.write_bytes(b'old thumbnail')

    content = BytesIO()
    Image.new('RGB', (32, 32), 'green').save(content, format='PNG')
    content.seek(0)
    app = type('AvatarApp', (), {
        'config': {'UPLOAD_FOLDER': str(tmp_path)},
        'logger': logging.getLogger('test-avatar'),
    })()
    previous_path = user.avatarpath
    new_path, error = save_avatar(
        FileStorage(stream=content, filename='replacement.png'), user, app,
    )
    assert error is None and new_path and new_path != AVATAR_URL_PREFIX + old_name
    job_ids = enqueue_avatar_replacement_cleanup(
        db_session, app, user.id, previous_path, new_path,
    )
    db_session.commit()

    assert len(job_ids) == 2
    assert db_session.query(UserDeletionFileJob).count() == 2
    assert old_file.exists() and old_thumbnail.exists()
    assert process_pending_file_jobs(db_session) == 0
    assert not old_file.exists() and not old_thumbnail.exists()
    assert db_session.query(UserDeletionFileJob).count() == 0
    assert db_session.get(User, user.id).avatarpath == new_path


def test_avatar_replacement_cleanup_keeps_file_shared_by_another_user(db_session, tmp_path):
    from types import SimpleNamespace
    from oneirodex.utils.avatar import AVATAR_URL_PREFIX
    from oneirodex.utils.user_deletion import enqueue_avatar_replacement_cleanup

    suffix = str(uuid4())[:8]
    owner = _make_user(f'avatar_shared_owner_{suffix}', 'user')
    other = _make_user(f'avatar_shared_other_{suffix}', 'user')
    old_name = f'{uuid4().hex}.png'
    old_path = AVATAR_URL_PREFIX + old_name
    owner.avatarpath = old_path
    other.avatarpath = old_path
    db_session.add_all([owner, other])
    db_session.commit()
    avatar_dir = tmp_path / 'images' / 'avatars_users'
    avatar_dir.mkdir(parents=True)
    old_file = avatar_dir / old_name
    old_file.write_bytes(b'shared avatar')

    owner.avatarpath = AVATAR_URL_PREFIX + f'{uuid4().hex}.png'
    jobs = enqueue_avatar_replacement_cleanup(
        db_session,
        SimpleNamespace(config={'UPLOAD_FOLDER': str(tmp_path)}),
        owner.id,
        old_path,
        owner.avatarpath,
    )
    db_session.commit()

    assert jobs == []
    assert db_session.query(UserDeletionFileJob).count() == 0
    assert old_file.read_bytes() == b'shared avatar'
