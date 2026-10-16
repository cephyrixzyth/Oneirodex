"""Optional library root-folder incremental watch (``ONEIRODEX_LIBRARY_WATCH`` / ``ONEIRODEX_LIBRARY_WATCH``).

Default **off**. When enabled, watches each library ``last_scan_folder`` with
scan-depth–aware event filtering (game-leaf / one level inside only — not deep
arcade ROM trees), debounces (≥2–5s), and **only enqueues** ScanJobs via
``scan_queue`` (cooperative with ``worker_caps`` / FIFO queue).
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import or_, select

from product_env import getenv_product
from oneirodex.utils.gamenames import LETTER_BUCKET_RE, should_skip_scan_dir

_watch_started = False
_controller: 'LibraryWatchController | None' = None

_DEFAULT_DEBOUNCE_SEC = 3.0
_MIN_DEBOUNCE_SEC = 2.0
_MAX_DEBOUNCE_SEC = 5.0
_ROOT_REFRESH_SEC = 60.0


def is_library_watch_enabled() -> bool:
    """True when ``ONEIRODEX_LIBRARY_WATCH`` / ``ONEIRODEX_LIBRARY_WATCH`` is truthy. Default off."""
    raw = getenv_product('LIBRARY_WATCH')
    if raw is None or str(raw).strip() == '':
        return False
    return str(raw).strip().lower() in ('1', 'true', 'yes', 'on')


def library_watch_debounce_seconds() -> float:
    """Debounce window; default 3s, clamped to 2–5. Override via env."""
    raw = getenv_product('LIBRARY_WATCH_DEBOUNCE_SEC')
    if raw is None or str(raw).strip() == '':
        return _DEFAULT_DEBOUNCE_SEC
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return _DEFAULT_DEBOUNCE_SEC
    return max(_MIN_DEBOUNCE_SEC, min(_MAX_DEBOUNCE_SEC, value))


def get_library_watch_status() -> dict:
    """Ops / services pulse for the incremental library watcher."""
    enabled = is_library_watch_enabled()
    ctrl = _controller
    if not enabled:
        return {
            'enabled': False,
            'running': False,
            'roots': 0,
            'pending_libraries': 0,
            'debounce_seconds': library_watch_debounce_seconds(),
            'last_event_at': None,
            'last_enqueue_at': None,
            'note': 'Set ONEIRODEX_LIBRARY_WATCH=1 to enable root-folder incremental watch.',
        }
    if ctrl is None:
        return {
            'enabled': True,
            'running': False,
            'roots': 0,
            'pending_libraries': 0,
            'debounce_seconds': library_watch_debounce_seconds(),
            'last_event_at': None,
            'last_enqueue_at': None,
            'note': 'Enabled but watcher not started (boot pending or start failed).',
        }
    return ctrl.status()


def normalize_fs_path(path: str | None) -> str:
    if not path:
        return ''
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


@dataclass
class WatchEvent:
    kind: str  # add | change | delete
    library_uuid: str
    library_root: str
    game_path: str


@dataclass
class PendingLibraryBatch:
    library_uuid: str
    library_root: str
    kinds: set[str] = field(default_factory=set)
    game_paths: set[str] = field(default_factory=set)


def classify_watch_path(
    root: str,
    event_path: str,
    scan_depth: int = 1,
    *,
    event_type: str = 'modified',
    is_directory: bool = False,
    skip_dir_patterns=None,
) -> dict | None:
    """Map a filesystem event to a game-leaf watch action, or None to ignore.

    Honors scan_depth (letter buckets at depth 2). Ignores paths deeper than
    game-leaf + one immediate child (avoids arcade ROM tree noise).
    """
    root_n = normalize_fs_path(root)
    path_n = normalize_fs_path(event_path)
    if not root_n or not path_n:
        return None
    try:
        rel = os.path.relpath(path_n, root_n)
    except ValueError:
        return None
    if rel.startswith('..') or rel in ('.', ''):
        return None

    parts = [p for p in rel.replace('\\', '/').split('/') if p]
    if not parts:
        return None

    depth = int(scan_depth or 1)
    if should_skip_scan_dir(parts[0], skip_dir_patterns):
        return None

    if depth >= 2 and LETTER_BUCKET_RE.match(parts[0]):
        if len(parts) == 1:
            # Letter bucket itself — not a game leaf.
            return None
        if should_skip_scan_dir(parts[1], skip_dir_patterns):
            return None
        game_rel_parts = parts[:2]
        max_parts = 3  # bucket / game / immediate child
        leaf_depth = 2
    else:
        game_rel_parts = parts[:1]
        max_parts = 2  # game / immediate child
        leaf_depth = 1

    if len(parts) > max_parts:
        return None

    game_path = normalize_fs_path(os.path.join(root_n, *game_rel_parts))
    et = (event_type or 'modified').lower()

    if et in ('deleted', 'moved') and len(parts) == leaf_depth:
        kind = 'delete'
    elif et in ('created', 'moved') and len(parts) == leaf_depth and is_directory:
        kind = 'add'
    elif et == 'created' and len(parts) == leaf_depth:
        # Created entry at leaf depth — treat folder-ish adds as add, else change.
        kind = 'add' if is_directory else 'change'
    else:
        kind = 'change'

    return {
        'kind': kind,
        'game_path': game_path,
        'library_root': root_n,
        'rel_parts': parts,
    }


def library_remove_missing_policy(library_uuid: str) -> bool:
    """Honor Admin remove-missing from the library's most recent ScanJob."""
    from oneirodex.runtime_native.db_session import native_db as db
    from oneirodex.models import ScanJob

    row = db.session.execute(
        select(ScanJob)
        .where(ScanJob.library_uuid == library_uuid)
        .order_by(ScanJob.last_run.desc().nullslast(), ScanJob.id.desc())
        .limit(1)
    ).scalars().first()
    if not row:
        return False
    return bool(row.setting_remove)


def has_active_or_queued_scan(library_uuid: str, folder_path: str) -> bool:
    """True when a Running/Stopping/Queued job already covers this library root."""
    from oneirodex.runtime_native.db_session import native_db as db
    from oneirodex.models import ScanJob

    folder_n = normalize_fs_path(folder_path)
    rows = db.session.execute(
        select(ScanJob).where(
            ScanJob.library_uuid == library_uuid,
            ScanJob.status.in_(('Running', 'Stopping', 'Queued')),
        )
    ).scalars().all()
    for row in rows:
        if normalize_fs_path(row.scan_folder or '') == folder_n:
            return True
        # Same library root often stored without normalize — also compare raw.
        if row.scan_folder and os.path.normpath(row.scan_folder) == os.path.normpath(folder_path):
            return True
    return False


def library_should_watch(lib) -> bool:
    """Whether this library participates under the env master switch.

    ``ONEIRODEX_LIBRARY_WATCH`` must be on for any watching (Unraid FUSE safety).
    Per-library ``watch_enabled``:
      - ``None`` (default) → follow global (watch when env on)
      - ``True`` → watch when env on
      - ``False`` → opt-out even when env on
    """
    if not is_library_watch_enabled():
        return False
    flag = getattr(lib, 'watch_enabled', None)
    # Explicit False only (None/True follow global). Avoid `not flag` so None stays in.
    if flag is False:
        return False
    return True


def library_watch_effective(lib) -> bool:
    """Public effective watch state for API payloads (env ∩ per-lib)."""
    return library_should_watch(lib)


def list_watchable_libraries() -> list[dict]:
    """Libraries with a readable ``last_scan_folder`` root that opt into watch."""
    from oneirodex.runtime_native.db_session import native_db as db
    from oneirodex.models import Library

    libs = db.session.execute(
        select(Library).where(
            Library.last_scan_folder.isnot(None),
            # null / True watch when env on; False = opt-out (SQL-side for honesty)
            or_(Library.watch_enabled.is_(None), Library.watch_enabled.is_(True)),
        )
    ).scalars().all()
    out = []
    for lib in libs:
        if not library_should_watch(lib):
            continue
        folder = (lib.last_scan_folder or '').strip()
        if not folder:
            continue
        if not os.path.isdir(folder):
            continue
        if not os.access(folder, os.R_OK):
            continue
        out.append({
            'uuid': lib.uuid,
            'name': lib.name,
            'folder': folder,
            'scan_depth': int(getattr(lib, 'scan_depth', 1) or 1),
            'watch_enabled': getattr(lib, 'watch_enabled', None),
        })
    return out


class LibraryWatchController:
    """Owns Observer lifecycle, debounce coalescing, and scan enqueue."""

    def __init__(
        self,
        app,
        *,
        debounce_seconds: float | None = None,
        enqueue_fn: Callable | None = None,
        observer_factory: Callable | None = None,
    ):
        self.app = app
        self.debounce_seconds = (
            debounce_seconds
            if debounce_seconds is not None
            else library_watch_debounce_seconds()
        )
        self._enqueue_fn = enqueue_fn
        self._observer_factory = observer_factory
        self._lock = threading.RLock()
        self._pending: dict[str, PendingLibraryBatch] = {}
        self._debounce_timer: threading.Timer | None = None
        self._observer = None
        self._root_meta: dict[str, dict] = {}  # normalized root → lib meta
        self._running = False
        self._last_event_at: str | None = None
        self._last_enqueue_at: str | None = None
        self._refresh_stop = threading.Event()
        self._refresh_thread: threading.Thread | None = None

    def status(self) -> dict:
        with self._lock:
            return {
                'enabled': True,
                'running': self._running,
                'roots': len(self._root_meta),
                'pending_libraries': len(self._pending),
                'debounce_seconds': self.debounce_seconds,
                'last_event_at': self._last_event_at,
                'last_enqueue_at': self._last_enqueue_at,
                'note': None if self._running else 'Watcher stopped.',
            }

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            try:
                self._ensure_observer()
            except Exception as exc:
                print(f'[LIBRARY WATCH] Failed to start observer: {exc}')
                return
            self._running = True
            self._refresh_stop.clear()
            self._refresh_thread = threading.Thread(
                target=self._root_refresh_loop,
                name='oneirodex-library-watch-refresh',
                daemon=True,
            )
            self._refresh_thread.start()
            print(
                f'[LIBRARY WATCH] Started (debounce={self.debounce_seconds:.1f}s, '
                f'roots={len(self._root_meta)})'
            )

    def stop(self) -> None:
        with self._lock:
            self._refresh_stop.set()
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
                self._debounce_timer = None
            if self._observer is not None:
                try:
                    self._observer.stop()
                    self._observer.join(timeout=5)
                except Exception:
                    pass
                self._observer = None
            self._root_meta.clear()
            self._pending.clear()
            self._running = False

    def _ensure_observer(self) -> None:
        if self._observer_factory is not None:
            observer = self._observer_factory()
        else:
            from watchdog.observers import Observer

            observer = Observer()
        self._observer = observer
        self._sync_watched_roots(start_observer=True)

    def _root_refresh_loop(self) -> None:
        while not self._refresh_stop.wait(_ROOT_REFRESH_SEC):
            try:
                with self.app.app_context():
                    with self._lock:
                        self._sync_watched_roots(start_observer=False)
            except Exception as exc:
                print(f'[LIBRARY WATCH] Root refresh error: {exc}')

    def _sync_watched_roots(self, *, start_observer: bool) -> None:
        """Schedule watches for current library roots (call under lock / app ctx)."""
        libs = list_watchable_libraries()
        new_meta: dict[str, dict] = {}
        for lib in libs:
            root_n = normalize_fs_path(lib['folder'])
            new_meta[root_n] = lib

        # Full reschedule when set changes (simple + correct for Unraid remounts).
        if set(new_meta.keys()) != set(self._root_meta.keys()) or start_observer:
            if self._observer is not None and getattr(self._observer, 'is_alive', lambda: False)():
                try:
                    self._observer.unschedule_all()
                except Exception:
                    pass
            self._root_meta = new_meta
            if self._observer is None:
                return
            handler = _WatchdogHandler(self)
            for root_n in self._root_meta:
                try:
                    # recursive=True but handler filters deep ROM noise.
                    self._observer.schedule(handler, root_n, recursive=True)
                except Exception as exc:
                    print(f'[LIBRARY WATCH] Cannot watch {root_n}: {exc}')
            if start_observer and not getattr(self._observer, 'is_alive', lambda: False)():
                self._observer.start()
            print(f'[LIBRARY WATCH] Watching {len(self._root_meta)} library root(s)')
        else:
            self._root_meta = new_meta

    def handle_raw_event(
        self,
        *,
        src_path: str,
        event_type: str,
        is_directory: bool,
        dest_path: str | None = None,
    ) -> None:
        """Public entry for watchdog or tests (synthetic events)."""
        paths = [src_path]
        if dest_path:
            paths.append(dest_path)

        with self._lock:
            roots = list(self._root_meta.items())

        for path in paths:
            path_n = normalize_fs_path(path)
            matched = None
            for root_n, meta in roots:
                if path_n == root_n or path_n.startswith(root_n + os.sep):
                    matched = (root_n, meta)
                    break
            if not matched:
                continue
            root_n, meta = matched
            classified = classify_watch_path(
                root_n,
                path_n,
                meta.get('scan_depth', 1),
                event_type=event_type,
                is_directory=is_directory,
            )
            if not classified:
                continue
            self._queue_classified(
                library_uuid=meta['uuid'],
                library_root=meta['folder'],
                kind=classified['kind'],
                game_path=classified['game_path'],
            )

    def _queue_classified(
        self,
        *,
        library_uuid: str,
        library_root: str,
        kind: str,
        game_path: str,
    ) -> None:
        with self._lock:
            batch = self._pending.get(library_uuid)
            if batch is None:
                batch = PendingLibraryBatch(
                    library_uuid=library_uuid,
                    library_root=library_root,
                )
                self._pending[library_uuid] = batch
            batch.kinds.add(kind)
            batch.game_paths.add(game_path)
            self._last_event_at = datetime.now(timezone.utc).isoformat()
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
            self._debounce_timer = threading.Timer(
                self.debounce_seconds,
                self._flush_pending,
            )
            self._debounce_timer.daemon = True
            self._debounce_timer.start()

    def _flush_pending(self) -> None:
        with self._lock:
            batches = list(self._pending.values())
            self._pending.clear()
            self._debounce_timer = None

        if not batches:
            return

        with self.app.app_context():
            for batch in batches:
                try:
                    self._enqueue_batch(batch)
                except Exception as exc:
                    print(
                        f'[LIBRARY WATCH] Enqueue failed for '
                        f'{batch.library_uuid}: {exc}'
                    )

    def _clear_restored_path_status(self, batch: PendingLibraryBatch) -> None:
        """On add/change, clear path_status missing→ok for restored game folders."""
        if not batch.game_paths:
            return
        if not (batch.kinds & {'add', 'change'}):
            return
        from oneirodex.runtime_native.db_session import native_db as db
        from oneirodex.utils.library_health import clear_restored_missing_path_status

        cleared = clear_restored_missing_path_status(
            batch.game_paths,
            library_uuid=batch.library_uuid,
        )
        if cleared:
            db.session.commit()
            print(
                f'[LIBRARY WATCH] Cleared path_status missing→ok for '
                f'{cleared} game(s) (library={batch.library_uuid})'
            )

    def _enqueue_batch(self, batch: PendingLibraryBatch) -> None:
        from oneirodex.utils.scan_queue import start_or_queue_scan

        folder = batch.library_root
        # Restore honesty before enqueue/skip — Ops pulse must not wait on scan end.
        self._clear_restored_path_status(batch)

        if has_active_or_queued_scan(batch.library_uuid, folder):
            print(
                f'[LIBRARY WATCH] Skip enqueue — scan already active/queued for '
                f'{folder} (kinds={sorted(batch.kinds)})'
            )
            return

        remove_missing = False
        force_updates = False
        if 'delete' in batch.kinds:
            remove_missing = library_remove_missing_policy(batch.library_uuid)
        if 'change' in batch.kinds:
            force_updates = True

        enqueue = self._enqueue_fn or start_or_queue_scan
        result = enqueue(
            folder_path=folder,
            library_uuid=batch.library_uuid,
            scan_mode='folders',
            remove_missing=remove_missing,
            force_updates_extras_scan=force_updates,
            queue_policy='queue',
            allow_force=False,
            app=self.app,
        )
        self._last_enqueue_at = datetime.now(timezone.utc).isoformat()
        print(
            f'[LIBRARY WATCH] Enqueued {result.get("status")} job '
            f'{result.get("job_id")} for {folder} '
            f'kinds={sorted(batch.kinds)} paths={len(batch.game_paths)} '
            f'remove_missing={remove_missing} force_updates={force_updates}'
        )


class _WatchdogHandler:
    """Thin adapter from watchdog events → LibraryWatchController."""

    def __init__(self, controller: LibraryWatchController):
        self.controller = controller

    def dispatch(self, event) -> None:
        # Compatible with FileSystemEventHandler.dispatch without subclassing
        # (keeps tests free of watchdog import when using synthetic events).
        if getattr(event, 'is_synthetic', False):
            return
        event_type = getattr(event, 'event_type', None) or 'modified'
        src_path = getattr(event, 'src_path', None) or ''
        dest_path = getattr(event, 'dest_path', None)
        is_directory = bool(getattr(event, 'is_directory', False))
        # Normalize watchdog moved → treat as delete+add via dest.
        if event_type == 'moved':
            self.controller.handle_raw_event(
                src_path=src_path,
                event_type='deleted',
                is_directory=is_directory,
            )
            if dest_path:
                self.controller.handle_raw_event(
                    src_path=dest_path,
                    event_type='created',
                    is_directory=is_directory,
                )
            return
        self.controller.handle_raw_event(
            src_path=src_path,
            event_type=event_type,
            is_directory=is_directory,
            dest_path=dest_path,
        )

    # watchdog FileSystemEventHandler API
    def on_any_event(self, event) -> None:
        self.dispatch(event)


def start_library_watch(app) -> LibraryWatchController | None:
    """Start the library watcher daemon (idempotent). No-op when disabled."""
    global _watch_started, _controller

    if not is_library_watch_enabled():
        print('[LIBRARY WATCH] Disabled (ONEIRODEX_LIBRARY_WATCH unset/off)')
        return None

    if _watch_started and _controller is not None:
        return _controller

    # Import check — fail soft with a clear log if watchdog missing.
    try:
        import watchdog  # noqa: F401
    except ImportError:
        print(
            '[LIBRARY WATCH] ONEIRODEX_LIBRARY_WATCH=1 but watchdog is not installed. '
            'Add watchdog to requirements and rebuild the image.'
        )
        return None

    _controller = LibraryWatchController(app)
    _controller.start()
    _watch_started = True
    return _controller


def _reset_library_watch_for_tests() -> None:
    """Test helper — stop and clear singleton state."""
    global _watch_started, _controller
    if _controller is not None:
        try:
            _controller.stop()
        except Exception:
            pass
    _controller = None
    _watch_started = False
