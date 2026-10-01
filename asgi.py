"""
ASGI config for Oneirodex production deployment.
This file wraps the Flask app to be compatible with ASGI servers like uvicorn
and provides async file streaming for downloads and static assets.

The WSGI bridge is a2wsgi, not asgiref. asgiref's ``WsgiToAsgi`` submits the
call into a ``CurrentThreadExecutor`` that can already be shut down when the
client goes away mid-request, so a cancelled request died as a 500 the
operator then had to explain (UID-052). a2wsgi runs the WSGI app on its own
thread pool and treats ``http.disconnect`` as a disconnect rather than a
broken executor.

Static assets and SSE still bypass the bridge, but not for that reason: see
``_handle_static`` and ``_handle_sse``.
"""

from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import re
import uuid
from pathlib import Path

import aiofiles
from a2wsgi import WSGIMiddleware

from oneirodex import create_app, db
from oneirodex.async_streaming import (
    async_generate_zipstream_response,
    create_async_streaming_response,
)
from oneirodex.models import DownloadRequest, Game, User
from oneirodex.utils.event_logging import log_system_event
from oneirodex.utils.library_acl import user_can_access_game
from oneirodex.utils.play_url import library_platform_key
from oneirodex.utils.rom_archive import (
    ArchiveRomError,
    bundle_playable_rom_zip,
    resolve_playable_rom_path,
)
from oneirodex.utils.security import get_allowed_base_directories, is_safe_path
from oneirodex.utils.security_headers import baseline_static_headers
from oneirodex.utils.library_paths import library_dir
from oneirodex.utils.static_files import resolve_served_static, static_access
from sqlalchemy import select


# Proper ASGI application with lifespan protocol support
class LazyASGIApp:
    def __init__(self):
        self._app = None
        self._flask_app = None
        self._init_lock = asyncio.Lock()
        self._static_root: Path | None = None

    async def _ensure_flask(self):
        """Create Flask + the WSGI bridge once, safely under concurrent first hits."""
        if self._app is not None:
            return
        async with self._init_lock:
            if self._app is not None:
                return
            self._flask_app = create_app()
            self._static_root = Path(self._flask_app.static_folder or '').resolve()
            self._app = WSGIMiddleware(self._flask_app)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            await self._handle_lifespan(receive, send)
        elif scope["type"] == "http":
            path = scope["path"]

            if path.startswith('/download_zip/') or path.startswith('/api/downloadrom/'):
                await self._handle_download(scope, receive, send)
                return

            # Long-lived SSE must not run through the WSGI bridge — a single
            # sync stream holds a bridge thread for the life of the connection
            # and freezes Discover/Admin/API fetches. True of any bridge.
            sse_key = path.rstrip('/') or '/'
            if sse_key in self._SSE_ROUTES:
                cfg = self._SSE_ROUTES[sse_key]
                await self._handle_sse(
                    scope,
                    receive,
                    send,
                    channel=cfg['channel'],
                    event_types=cfg['event_types'],
                    restrict_child=cfg['restrict_child'],
                )
                return

            # Serve /static/* natively. This began as a workaround for the
            # asgiref bridge failing under concurrent CSS/JS, which a2wsgi has
            # now retired — it stays because the native path streams with
            # aiofiles and owns its own cache-control and security headers.
            if path.startswith('/static/'):
                await self._handle_static(scope, receive, send, path)
                return

            await self._ensure_flask()
            await self._app(scope, receive, send)

    # path (no trailing slash) → native async SSE config
    _SSE_ROUTES = {
        '/api/activity/stream': {
            'channel': 'activity',
            'event_types': frozenset({'activity', 'presence', 'hello', 'test'}),
            'restrict_child': True,
        },
        '/api/events/stream': {
            'channel': 'events',
            # scan/download/ops fan-out — emit all bus types
            'event_types': None,
            'restrict_child': False,
        },
    }

    def _event_visible(self, event, user_id) -> bool:
        """Per-viewer filter for the live streams (utils/event_visibility.py)."""
        payload = getattr(event, 'payload', None) or {}
        if payload.get('user_id') is None and not payload.get('game_uuid'):
            return True  # about no member and no game: no lookup needed
        try:
            with self._flask_app.app_context():
                from oneirodex import db
                from oneirodex.utils.event_visibility import event_visible_to

                try:
                    return event_visible_to(event, user_id)
                finally:
                    db.session.remove()
        except Exception:  # noqa: BLE001 — when in doubt, do not send it
            return False

    async def _authorize_sse_user(self, user_id, *, restrict_child: bool) -> int | None:
        """Return HTTP error status, or None if the user may open SSE."""
        if not user_id:
            return 401
        with self._flask_app.app_context():
            from oneirodex.utils.rbac import normalize_role

            user = db.session.get(User, user_id)
            if not user:
                return 401
            if restrict_child and normalize_role(getattr(user, 'role', None)) == 'child':
                return 403
        return None

    async def _handle_sse(
        self,
        scope,
        receive,
        send,
        *,
        channel: str,
        event_types: frozenset[str] | None,
        restrict_child: bool,
    ):
        """Async SSE — keeps the uvicorn event loop free (not WsgiToAsgi)."""
        import queue as queue_mod

        if scope.get("method") != "GET":
            await self._send_error(send, 405, "Method Not Allowed")
            return

        await self._ensure_flask()
        user_id = await self._get_user_from_session(scope)
        auth_status = await self._authorize_sse_user(user_id, restrict_child=restrict_child)
        if auth_status is not None:
            await self._send_error(
                send,
                auth_status,
                "Unauthorized" if auth_status == 401 else "Restricted",
            )
            return

        from oneirodex.utils.event_bus import encode_sse, event_bus

        subscriber = event_bus.subscribe()

        def _poll(timeout: float = 1.0):
            try:
                return subscriber.get(timeout=timeout)
            except queue_mod.Empty:
                return None

        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": [
                (b"content-type", b"text/event-stream"),
                (b"cache-control", b"no-cache"),
                (b"x-accel-buffering", b"no"),
                (b"connection", b"keep-alive"),
            ],
        })

        disconnected = asyncio.Event()

        async def _watch_disconnect():
            while True:
                message = await receive()
                if message.get("type") == "http.disconnect":
                    disconnected.set()
                    return

        hello = (
            f'event: hello\ndata: {{"ok": true, "channel": "{channel}"}}\n\n'
        ).encode('utf-8')
        watcher = asyncio.create_task(_watch_disconnect())
        try:
            await send({
                "type": "http.response.body",
                "body": hello,
                "more_body": True,
            })
            while not disconnected.is_set():
                event = await asyncio.to_thread(_poll, 1.0)
                if disconnected.is_set():
                    break
                if event is None:
                    await send({
                        "type": "http.response.body",
                        "body": b": keepalive\n\n",
                        "more_body": True,
                    })
                    continue
                if (event_types is None or event.type in event_types) and await asyncio.to_thread(
                    self._event_visible, event, user_id,
                ):
                    await send({
                        "type": "http.response.body",
                        "body": encode_sse(event),
                        "more_body": True,
                    })
        except (asyncio.CancelledError, ConnectionResetError, BrokenPipeError):
            pass
        except Exception as exc:
            print(f"Error in {channel} SSE: {exc}")
        finally:
            watcher.cancel()
            try:
                await watcher
            except asyncio.CancelledError:
                pass
            event_bus.unsubscribe(subscriber)
            try:
                await send({"type": "http.response.body", "body": b"", "more_body": False})
            except Exception:
                pass

    async def _handle_static(self, scope, receive, send, path: str):
        """Stream static files with path-traversal protection."""
        if scope.get("method") not in ("GET", "HEAD"):
            await self._send_error(send, 405, "Method Not Allowed")
            return

        await self._ensure_flask()
        root = self._static_root
        if root is None or not root.is_dir():
            await self._send_error(send, 500, "Static root not configured")
            return

        # Members' private files under /static/library/ are never static; BIOS
        # needs a signed-in member. 404 either way, so nothing is confirmed.
        access = static_access(root, path)
        if access == 'private' or (access == 'member' and await self._get_user_from_session(scope) is None):
            await self._send_error(send, 404, "Not Found")
            return

        candidate = resolve_served_static(root, path)
        if candidate is None:
            await self._send_error(send, 404, "Not Found")
            return

        if not candidate.is_file():
            await self._send_error(send, 404, "Not Found")
            return

        content_type, _ = mimetypes.guess_type(str(candidate))
        if not content_type:
            content_type = 'application/octet-stream'
        # CSS/JS under themes often mis-detected on some platforms
        lower = candidate.name.lower()
        if lower.endswith('.css'):
            content_type = 'text/css; charset=utf-8'
        elif lower.endswith('.js'):
            content_type = 'application/javascript; charset=utf-8'
        elif lower.endswith('.map'):
            content_type = 'application/json'
        elif lower.endswith('.svg'):
            content_type = 'image/svg+xml'
        elif lower.endswith('.woff2'):
            content_type = 'font/woff2'
        elif lower.endswith('.woff'):
            content_type = 'font/woff'

        try:
            size = candidate.stat().st_size
        except OSError:
            await self._send_error(send, 404, "Not Found")
            return

        # Two families of file are rewritten in place at a stable path, so an
        # hour of blind caching hides a change that has already shipped. Images
        # and fonts are genuinely static and keep the hour.
        #
        # Theme files are rewritten by Reset Themes while every template keeps
        # pointing at the same path. `theme_asset` versions those URLs, and this
        # is the second half: even an unversioned reference revalidates instead
        # of being assumed fresh.
        normalized = path.replace('\\', '/')
        is_mutable_theme_asset = '/static/library/themes/' in normalized
        # The SPA *entry* bundle is unhashed on purpose so Jinja can link it,
        # and the `?v=` on that link makes the script tag fetch fresh. But the
        # lazy route chunks `import` the entry by its bare path, with no query,
        # and that unversioned URL was cached for an hour — so after a rebuild
        # every lazily-loaded route went on running the *previous* build's
        # shared code while the versioned script tag reported the new one.
        # Observed directly: a fixed component kept rendering its old markup,
        # and `performance` showed two fetches of member-app.js at two sizes.
        # `chunks/` keeps the hour — those names carry a content hash, so a new
        # build is a new URL and caching them hard is the point.
        is_spa_entry = '/static/dist/' in normalized and '/chunks/' not in normalized
        cache_control = (
            b"no-cache"
            if (is_mutable_theme_asset or is_spa_entry)
            else b"public, max-age=3600"
        )

        # Static is served here, outside the WSGI bridge, so Flask's
        # after_request never sees it — these have to be stamped again rather
        # than inherited.
        # Baseline only, no CSP: webretro.html is a static document whose
        # Emscripten cores would need 'unsafe-eval' anyway.
        headers = [
            (b"content-type", content_type.encode("ascii", "ignore")),
            (b"content-length", str(size).encode()),
            (b"cache-control", cache_control),
            *baseline_static_headers(),
        ]

        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": headers,
        })

        if scope.get("method") == "HEAD":
            await send({"type": "http.response.body", "body": b"", "more_body": False})
            return

        try:
            async with aiofiles.open(candidate, "rb") as fh:
                while True:
                    chunk = await fh.read(65536)
                    if not chunk:
                        break
                    await send({
                        "type": "http.response.body",
                        "body": chunk,
                        "more_body": True,
                    })
            await send({"type": "http.response.body", "body": b"", "more_body": False})
        except Exception as exc:
            print(f"Error streaming static {path}: {exc}")
            try:
                await send({"type": "http.response.body", "body": b"", "more_body": False})
            except Exception:
                pass

    async def _handle_download(self, scope, receive, send):
        """Handle download routes with async file streaming"""
        path = scope["path"]
        method = scope["method"]

        if method != "GET":
            await self._send_error(send, 405, "Method Not Allowed")
            return

        try:
            await self._ensure_flask()

            if path.startswith('/download_zip/'):
                await self._handle_zip_download(scope, receive, send, path)
            elif path.startswith('/api/downloadrom/'):
                await self._handle_rom_download(scope, receive, send, path)

        except Exception as e:
            print(f"Error in async download handler: {str(e)}")
            try:
                await self._send_error(send, 500, "Internal Server Error")
            except Exception as error_e:
                print(f"Could not send error response (response may have already started): {str(error_e)}")
                try:
                    await send({
                        "type": "http.response.body",
                        "body": b"",
                        "more_body": False
                    })
                except Exception:
                    pass

    async def _handle_zip_download(self, scope, receive, send, path):
        """Handle ZIP file downloads"""
        download_id_match = re.match(r'/download_zip/(\d+)', path)
        if not download_id_match:
            await self._send_error(send, 400, "Invalid download ID")
            return

        download_id = int(download_id_match.group(1))

        user_id = await self._get_user_id(scope)
        if not user_id:
            await self._send_error(send, 401, "Unauthorized")
            return

        with self._flask_app.app_context():
            download_request = db.session.execute(
                select(DownloadRequest).filter_by(id=download_id, user_id=user_id)
            ).scalars().first()

            if not download_request:
                await self._send_error(send, 404, "Download not found")
                return

            if download_request.status != 'available':
                await self._send_error(send, 400, "Download not ready")
                return

            file_path = download_request.zip_file_path

            if os.path.isdir(file_path):
                await self._handle_streaming_download(send, download_request, file_path)
                return

            allowed_bases = get_allowed_base_directories(self._flask_app)
            if not allowed_bases:
                await self._send_error(send, 500, "Server configuration error")
                return

            is_safe, error_message = is_safe_path(file_path, allowed_bases)
            if not is_safe:
                log_system_event(
                    f"Security violation - game file outside allowed directories: {file_path[:100]}",
                    event_type='security',
                    event_level='warning',
                )
                await self._send_error(send, 403, "Access denied")
                return

            if not os.path.exists(file_path):
                await self._send_error(send, 404, "File not found")
                return

            filename = os.path.basename(file_path)
            log_system_event(
                f"Async file download: {filename}",
                event_type='download',
                event_level='information',
            )
            await self._stream_file(send, file_path, filename)

    async def _handle_rom_download(self, scope, receive, send, path):
        """Handle ROM file downloads for emulator"""
        rom_match = re.match(r'/api/downloadrom/([a-f0-9-]+)', path)
        if not rom_match:
            await self._send_error(send, 400, "Invalid game UUID")
            return

        game_uuid = rom_match.group(1)

        try:
            uuid.UUID(game_uuid)
        except ValueError:
            log_system_event(
                f"Invalid UUID format attempted for ROM download: {game_uuid}",
                event_type='security',
                event_level='warning',
            )
            await self._send_error(send, 400, "Invalid game identifier")
            return

        user_id = await self._get_user_id(scope)
        if not user_id:
            await self._send_error(send, 401, "Unauthorized")
            return

        with self._flask_app.app_context():
            game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()

            if not game:
                log_system_event(
                    f"ROM download attempt for non-existent game UUID: {game_uuid}",
                    event_type='security',
                    event_level='warning',
                )
                await self._send_error(send, 404, "Game not found")
                return

            user = db.session.get(User, user_id)
            if not user or not user_can_access_game(user, game):
                log_system_event(
                    f"ROM download blocked by library ACL for user_id={user_id} game={game_uuid[:8]}...",
                    event_type='security',
                    event_level='warning',
                )
                await self._send_error(send, 403, "Access denied")
                return

            if not os.path.exists(game.full_disk_path):
                log_system_event(
                    f"ROM download attempt for missing file: {game.name} at {game.full_disk_path}",
                    event_type='security',
                    event_level='warning',
                )
                await self._send_error(send, 404, "ROM file not found on disk")
                return

            allowed_bases = get_allowed_base_directories(self._flask_app)
            is_safe, error_message = is_safe_path(game.full_disk_path, allowed_bases)

            if not is_safe:
                log_system_event(
                    f"Path traversal attempt blocked for ROM download: {game.full_disk_path} - {error_message}",
                    event_type='security',
                    event_level='warning',
                )
                await self._send_error(send, 403, "Access denied")
                return

            cache_dir = os.path.join(library_dir(self._flask_app.root_path), 'rom_cache', game_uuid)
            platform_key = library_platform_key(game)
            try:
                rom_path, filename = resolve_playable_rom_path(
                    game.full_disk_path,
                    cache_dir=cache_dir,
                    platform=platform_key,
                )
                # Multi-track discs (.cue + .bin/.img/...) need every file in one
                # response — WebRetro never gets a second chance to fetch companions.
                rom_path, filename = bundle_playable_rom_zip(rom_path, cache_dir)
            except ArchiveRomError as exc:
                log_system_event(
                    f"ROM resolve failed for {game.name}: {exc.message}",
                    event_type='download',
                    event_level='warning',
                )
                await self._send_error(
                    send,
                    exc.status_code,
                    exc.message,
                    code=exc.code,
                    hint=exc.hint,
                )
                return

            log_system_event(
                f"ROM file downloaded for WebRetro: {game.name}",
                event_type='download',
                event_level='information',
            )
            await self._stream_file(send, rom_path, filename)

    async def _get_user_id(self, scope):
        """Resolve user id from Bearer token (API clients) or Flask session cookie (web)."""
        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode("utf-8")
        if auth_header.lower().startswith("bearer "):
            await self._ensure_flask()
            with self._flask_app.app_context():
                from oneirodex.utils.api_tokens import verify_bearer_token

                raw = auth_header.split(" ", 1)[1].strip()
                user, token = verify_bearer_token(raw)
                if user and token and token.has_scope('write:download'):
                    return user.id
            return None

        return await self._get_user_from_session(scope)

    async def _get_user_from_session(self, scope):
        """Extract user ID from Flask session cookie"""
        headers = dict(scope.get("headers", []))
        cookie_header = headers.get(b"cookie", b"").decode("utf-8")

        if not cookie_header:
            return None

        cookies = {}
        for cookie in cookie_header.split(';'):
            if '=' in cookie:
                name, value = cookie.strip().split('=', 1)
                cookies[name] = value

        session_cookie = cookies.get('session')
        if not session_cookie:
            return None

        try:
            await self._ensure_flask()
            with self._flask_app.app_context():
                from flask import Request
                from flask.sessions import SecureCookieSessionInterface

                session_interface = SecureCookieSessionInterface()
                environ = {
                    'REQUEST_METHOD': 'GET',
                    'PATH_INFO': '/',
                    'SERVER_NAME': 'localhost',
                    'SERVER_PORT': '5000',
                    'HTTP_COOKIE': cookie_header,
                    'wsgi.url_scheme': 'http',
                }
                request = Request(environ)
                session_data = session_interface.open_session(self._flask_app, request)
                if session_data:
                    user_id = session_data.get('_user_id')
                    if user_id:
                        # The same check as Flask-Login's loader: a disabled
                        # account or a changed password ends the session here too.
                        from oneirodex.utils.auth import load_user

                        user = load_user(user_id)
                        return user.id if user is not None else None
                return None

        except Exception as e:
            log_system_event(
                f"Error parsing Flask session cookie: {str(e)}",
                event_type='security',
                event_level='warning',
            )
            return None

    async def _stream_file(self, send, file_path, filename):
        """Stream a file asynchronously"""
        try:
            async_generator, headers = await create_async_streaming_response(file_path, filename)

            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
            })

            async for chunk in async_generator:
                await send({
                    "type": "http.response.body",
                    "body": chunk,
                    "more_body": True,
                })

            await send({
                "type": "http.response.body",
                "body": b"",
                "more_body": False,
            })

        except Exception as e:
            log_system_event(
                f"Error streaming file {filename}: {str(e)}",
                event_type='download',
                event_level='error',
            )
            await self._send_error(send, 500, "Error streaming file")

    async def _handle_streaming_download(self, send, download_request, source_path):
        """Handle zipstream downloads for multi-file games"""
        try:
            allowed_bases = get_allowed_base_directories(self._flask_app)
            if not allowed_bases:
                await self._send_error(send, 500, "Server configuration error")
                return

            is_safe, error_message = is_safe_path(source_path, allowed_bases)
            if not is_safe:
                print(f"Security violation - streaming source outside allowed directories: {source_path[:100]}")
                await self._send_error(send, 403, "Access denied")
                return

            if not os.path.exists(source_path):
                await self._send_error(send, 404, "Source path not found")
                return

            chunk_size = self._flask_app.config.get('ZIPSTREAM_CHUNK_SIZE', 65536)
            compression_level = self._flask_app.config.get('ZIPSTREAM_COMPRESSION_LEVEL', 0)
            enable_zip64 = self._flask_app.config.get('ZIPSTREAM_ENABLE_ZIP64', True)

            if download_request.file_location:
                base_name = os.path.basename(download_request.file_location)
                filename = f"{base_name}.zip" if not base_name.lower().endswith('.zip') else base_name
            else:
                game = download_request.game
                filename = f"{game.name}.zip" if game else "download.zip"

            print(f"Starting zipstream download: {filename}")

            async_generator, headers = async_generate_zipstream_response(
                source_path, filename, chunk_size, compression_level, enable_zip64
            )

            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
            })

            async for chunk in async_generator:
                await send({
                    "type": "http.response.body",
                    "body": chunk,
                    "more_body": True,
                })

            await send({
                "type": "http.response.body",
                "body": b"",
                "more_body": False,
            })

            print(f"Completed zipstream download: {filename}")

        except Exception as e:
            error_filename = locals().get('filename', 'unknown')
            print(f"Error streaming ZIP {error_filename}: {str(e)}")
            try:
                await self._send_error(send, 500, "Error streaming ZIP file")
            except Exception:
                try:
                    await send({
                        "type": "http.response.body",
                        "body": b"",
                        "more_body": False,
                    })
                except Exception:
                    pass

    async def _send_error(self, send, status_code, message, *, code=None, hint=None):
        """Send an HTTP error response (JSON). Optional code/hint for ROM extract failures."""
        payload = {"error": message}
        if code:
            payload["code"] = code
        if hint:
            payload["hint"] = hint
        response_body = json.dumps(payload).encode()

        await send({
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(response_body)).encode()),
            ],
        })

        await send({
            "type": "http.response.body",
            "body": response_body,
            "more_body": False,
        })

    async def _handle_lifespan(self, receive, send):
        """Handle ASGI lifespan events (startup/shutdown)"""
        message = await receive()

        if message["type"] == "lifespan.startup":
            try:
                from oneirodex.utils.shutdown import register_shutdown_handlers

                register_shutdown_handlers()
                # Eager-init Flask so the first browser burst does not race bridge setup.
                await self._ensure_flask()

                # Background schedulers live here now, not in create_app().
                # Wrapped so a scheduler that throws on start can never wedge
                # lifespan and take the whole server down with it.
                try:
                    from oneirodex.background import start_background_workers

                    start_background_workers(self._flask_app)
                except Exception as e:
                    print(f"Background workers failed to start: {e}")

                await send({"type": "lifespan.startup.complete"})
            except Exception as e:
                print(f"Startup failed: {e}")
                await send({"type": "lifespan.startup.failed", "message": "Startup failed"})

        elif message["type"] == "lifespan.shutdown":
            try:
                from oneirodex.utils.shutdown import request_shutdown

                try:
                    from oneirodex.background import stop_background_workers

                    stop_background_workers()
                except Exception as e:
                    print(f"Background workers failed to stop cleanly: {e}")

                request_shutdown()
                print("🛑 ASGI lifespan shutdown initiated")
                await send({"type": "lifespan.shutdown.complete"})
            except Exception as e:
                print(f"Shutdown failed: {e}")
                await send({"type": "lifespan.shutdown.failed", "message": "Shutdown failed"})


asgi_app = LazyASGIApp()
