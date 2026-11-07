"""Shared account-deletion relation handling for Flask and native routes."""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError


def _storage_roots() -> tuple[Path, Path]:
    from oneirodex.utils.runtime_config import get_runtime_config
    from oneirodex.utils.library_paths import library_dir

    config = get_runtime_config() or {}
    upload = Path(config.get('UPLOAD_FOLDER') or library_dir()).resolve()
    saves = Path(config.get('EMULATOR_SAVES_PATH') or (upload / 'saves')).resolve()
    return upload, saves


def _relative_path(root: Path, path: str) -> str:
    target = Path(os.path.abspath(path))
    try:
        return target.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError('User file is outside its configured storage root') from exc


def _user_file_candidates(session, user) -> list[tuple[str, str, str]]:
    """Return (kind, resolved root, relative file) candidates, never caller paths."""
    from oneirodex.models import (
        ChatMessageAttachment,
        EmulatorSave,
        EmulatorSaveGeneration,
    )
    from oneirodex.utils.avatar import AVATAR_URL_PREFIX, is_shipped_avatar

    upload_root, saves_root = _storage_roots()
    candidates: set[tuple[str, str, str]] = set()

    avatar_path = user.avatarpath or ''
    if avatar_path.startswith(AVATAR_URL_PREFIX) and not is_shipped_avatar(avatar_path):
        filename = Path(avatar_path).name
        if filename and filename == avatar_path[len(AVATAR_URL_PREFIX):]:
            for name in (filename, _thumbnail_name(filename)):
                candidates.add(('avatar', str(upload_root), f'images/avatars_users/{name}'))

    attachments = session.execute(
        select(ChatMessageAttachment.file_name).where(
            ChatMessageAttachment.uploaded_by_user_id == user.id,
        ),
    ).scalars()
    for filename in attachments:
        if filename and Path(filename).name == filename:
            candidates.add(('attachment', str(upload_root), f'chat-attachments/{filename}'))

    saves = list(session.execute(
        select(EmulatorSave).where(EmulatorSave.user_id == user.id),
    ).scalars())
    save_paths: set[str] = {row.storage_path for row in saves if row.storage_path}
    save_ids = [row.id for row in saves]
    if save_ids:
        save_paths.update(
            path for path in session.execute(
                select(EmulatorSaveGeneration.storage_path).where(
                    EmulatorSaveGeneration.save_id.in_(save_ids),
                ),
            ).scalars() if path
        )
    for path in save_paths:
        relative = _relative_path(saves_root, path)
        candidates.add(('save', str(saves_root), relative))

    return sorted(candidates)


def _thumbnail_name(filename: str) -> str:
    stem, extension = os.path.splitext(filename)
    return f'{stem}_thumbnail{extension}'


def _candidate_still_referenced(
    session, kind: str, root: str, relative: str, *, exclude_user_id: int | None = None,
) -> bool:
    from oneirodex.models import (
        ChatMessageAttachment,
        EmulatorSave,
        EmulatorSaveGeneration,
        User,
    )
    from oneirodex.utils.avatar import AVATAR_URL_PREFIX

    absolute = os.path.abspath(Path(root) / relative)
    if kind == 'avatar':
        name = Path(relative).name
        stem, extension = os.path.splitext(name)
        if stem.endswith('_thumbnail'):
            name = f'{stem[:-10]}{extension}'
        stored = AVATAR_URL_PREFIX + name
        statement = select(User.id).where(User.avatarpath == stored)
        if exclude_user_id is not None:
            statement = statement.where(User.id != exclude_user_id)
        return session.execute(statement.limit(1)).first() is not None
    if kind == 'attachment':
        return session.execute(
            select(ChatMessageAttachment.id).where(
                ChatMessageAttachment.file_name == Path(relative).name,
            ).limit(1),
        ).first() is not None
    if kind == 'save':
        return (
            session.execute(
                select(EmulatorSave.id).where(EmulatorSave.storage_path == absolute).limit(1),
            ).first() is not None
            or session.execute(
                select(EmulatorSaveGeneration.id).where(
                    EmulatorSaveGeneration.storage_path == absolute,
                ).limit(1),
            ).first() is not None
        )
    raise ValueError('Unknown user deletion file kind')


def _enqueue_file_candidates(
    session,
    candidates: list[tuple[str, str, str]],
    *,
    exclude_avatar_user_id: int | None = None,
) -> list[int]:
    from oneirodex.models import UserDeletionFileJob

    job_ids = []
    for kind, root, relative in candidates:
        if _candidate_still_referenced(
            session,
            kind,
            root,
            relative,
            exclude_user_id=exclude_avatar_user_id if kind == 'avatar' else None,
        ):
            existing = session.execute(
                select(UserDeletionFileJob).where(
                    UserDeletionFileJob.root_path == root,
                    UserDeletionFileJob.relative_path == relative,
                ).limit(1),
            ).scalars().first()
            if existing is not None:
                session.delete(existing)
            continue
        job = session.execute(
            select(UserDeletionFileJob).where(
                UserDeletionFileJob.root_path == root,
                UserDeletionFileJob.relative_path == relative,
            ).limit(1),
        ).scalars().first()
        if job is None:
            path_key = hashlib.sha256(f'{root}\0{relative}'.encode('utf-8')).hexdigest()
            job = UserDeletionFileJob(
                path_key=path_key,
                root_path=root,
                relative_path=relative,
            )
            try:
                with session.begin_nested():
                    session.add(job)
                    session.flush()
            except IntegrityError:
                job = session.execute(
                    select(UserDeletionFileJob).where(
                        UserDeletionFileJob.root_path == root,
                        UserDeletionFileJob.relative_path == relative,
                    ).limit(1),
                ).scalars().first()
                if job is None:
                    raise
        job_ids.append(job.id)
    session.flush()
    return job_ids


def enqueue_avatar_replacement_cleanup(
    session, app, user_id: int, previous_path: str | None, new_path: str | None,
) -> list[int]:
    """Queue old avatar bytes in the same transaction as the avatar pointer update."""
    from oneirodex.utils.avatar import AVATAR_URL_PREFIX, is_shipped_avatar

    if not previous_path or previous_path == new_path:
        return []
    if not previous_path.startswith(AVATAR_URL_PREFIX) or is_shipped_avatar(previous_path):
        return []
    filename = Path(previous_path).name
    if not filename or filename != previous_path[len(AVATAR_URL_PREFIX):]:
        return []
    upload_root = Path(app.config.get('UPLOAD_FOLDER') or _storage_roots()[0]).resolve()
    stem, extension = os.path.splitext(filename)
    candidates = [
        ('avatar', str(upload_root), f'images/avatars_users/{filename}'),
        ('avatar', str(upload_root), f'images/avatars_users/{stem}_thumbnail{extension}'),
    ]
    return _enqueue_file_candidates(
        session, candidates, exclude_avatar_user_id=user_id,
    )


def process_pending_file_jobs(session, *, limit: int = 100) -> int:
    """Purge queued files safely; return the number still awaiting cleanup."""
    from oneirodex.models import UserDeletionFileJob

    jobs = list(session.execute(
        select(UserDeletionFileJob)
        .where(UserDeletionFileJob.state.in_(('pending', 'failed')))
        .order_by(UserDeletionFileJob.id)
        .limit(limit)
        .with_for_update(skip_locked=True),
    ).scalars())
    for job in jobs:
        job.attempts += 1
        try:
            root = Path(job.root_path).resolve()
            relative = Path(job.relative_path)
            expected_key = hashlib.sha256(
                f'{job.root_path}\0{job.relative_path}'.encode('utf-8'),
            ).hexdigest()
            if job.path_key != expected_key:
                raise ValueError('path_key_mismatch')
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('unsafe_relative_path')
            target = root / relative
            parent = target.parent
            while parent != root:
                if parent.is_symlink():
                    raise ValueError('unsafe_symlink_parent')
                parent = parent.parent
            if target.is_symlink():
                raise ValueError('unsafe_symlink_target')
            target.parent.resolve().relative_to(root)
            target.unlink(missing_ok=True)
            session.delete(job)
        except Exception as exc:  # retain a path-free retry record
            job.state = 'failed'
            job.last_error_code = (
                'unsafe_path' if isinstance(exc, ValueError)
                else type(exc).__name__[:64]
            )
    session.commit()
    return int(session.execute(
        select(func.count()).select_from(UserDeletionFileJob).where(
            UserDeletionFileJob.state.in_(('pending', 'failed')),
        ),
    ).scalar_one())


def delete_user_account(session, user) -> int:
    """Delete DB-owned data atomically, then purge safe owned files after commit."""
    candidates = _user_file_candidates(session, user)
    anonymize_user_audit_events(session, user)
    delete_user_owned_rows(session, user)
    session.delete(user)
    session.flush()
    job_ids = _enqueue_file_candidates(session, candidates)
    session.commit()
    try:
        process_pending_file_jobs(session)
        if not job_ids:
            return 0
        from oneirodex.models import UserDeletionFileJob
        return int(session.execute(
            select(func.count()).select_from(UserDeletionFileJob).where(
                UserDeletionFileJob.id.in_(job_ids),
                UserDeletionFileJob.state.in_(('pending', 'failed')),
            ),
        ).scalar_one())
    except Exception:
        session.rollback()
        return max(1, len(job_ids))


class _FileCleanupWorker:
    def __init__(self):
        import threading

        self.stop_event = threading.Event()

    def stop(self):
        self.stop_event.set()
        global _worker_started
        if _worker_lock is not None:
            with _worker_lock:
                _worker_started = False


_worker_lock = None
_worker_started = False


def start_file_cleanup_worker(app, *, interval_seconds: int = 60):
    """Retry failed deletion-file jobs after startup and periodically."""
    import threading

    global _worker_lock, _worker_started
    if _worker_lock is None:
        _worker_lock = threading.Lock()
    with _worker_lock:
        if _worker_started:
            return None
        _worker_started = True

    handle = _FileCleanupWorker()

    def run():
        while not handle.stop_event.is_set():
            try:
                with app.app_context():
                    from oneirodex.runtime_native.db_session import native_db
                    remaining = process_pending_file_jobs(native_db.session)
                    if remaining:
                        app.logger.warning(
                            'Account deletion file cleanup remains pending (%s jobs)',
                            remaining,
                        )
            except Exception as exc:
                try:
                    native_db.session.rollback()
                except Exception:
                    pass
                app.logger.warning(
                    'Account deletion file cleanup retry failed (%s)',
                    type(exc).__name__,
                )
            handle.stop_event.wait(interval_seconds)

    thread = threading.Thread(
        target=run,
        name='user-deletion-file-cleanup',
        daemon=True,
    )
    thread.start()
    handle.thread = thread
    return handle


def anonymize_user_audit_events(session, user) -> None:
    """Keep useful audit history while removing direct identifiers for a user."""
    from oneirodex.models import SystemEvents

    identifiers = [value for value in (user.name, user.email, user.user_id) if value]
    predicates = [SystemEvents.audit_user == user.id]
    predicates.extend(
        SystemEvents.event_text.contains(value, autoescape=True)
        for value in identifiers
    )
    events = session.execute(
        select(SystemEvents).where(or_(*predicates)).with_for_update()
    ).scalars()
    for event in events:
        text = event.event_text
        for value in identifiers:
            text = re.sub(re.escape(value), '[deleted account]', text, flags=re.IGNORECASE)
        event.event_text = text
        if event.audit_user == user.id:
            event.audit_user = None


def delete_user_owned_rows(session, user) -> None:
    """Delete private rows and anonymize references to retained audit records."""
    from oneirodex.models import (
        DownloadRequest,
        DuplicateFixLog,
        InviteToken,
        Newsletter,
        UserAttractModeSettings,
        user_favorites,
        user_game_status,
    )

    # These tables have no ORM ownership cascade or database ON DELETE action.
    session.execute(delete(user_favorites).where(user_favorites.c.user_id == user.id))
    session.execute(delete(user_game_status).where(user_game_status.c.user_id == user.id))
    session.execute(delete(DownloadRequest).where(DownloadRequest.user_id == user.id))
    session.execute(delete(Newsletter).where(Newsletter.sender_id == user.id))
    session.execute(delete(InviteToken).where(InviteToken.creator_user_id == user.user_id))
    session.execute(
        update(InviteToken).where(InviteToken.used_by == user.user_id).values(used_by=None)
    )
    session.execute(
        delete(UserAttractModeSettings).where(
            UserAttractModeSettings.user_id == user.user_id
        )
    )
    session.execute(
        update(DuplicateFixLog)
        .where(DuplicateFixLog.actor_user_id == user.id)
        .values(actor_user_id=None)
    )
