"""Native admin read for the custom chat emoji catalogue."""
from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable

from fastapi import APIRouter, FastAPI, Request
from starlette.responses import JSONResponse, RedirectResponse

from .oidc_status import _login_redirect
from .request_auth import request_auth_context


class ChatEmojiData:
    def member_read(self) -> dict:
        from oneirodex.utils.custom_emoji import ALLOWED_REACTIONS, MAX_CUSTOM_EMOJI, list_custom_emoji

        return {
            'fixed': sorted(ALLOWED_REACTIONS),
            'custom': list_custom_emoji(),
            'max_custom': MAX_CUSTOM_EMOJI,
        }

    def read(self) -> dict:
        from oneirodex.utils.custom_emoji import (
            ALLOWED_EXT,
            MAX_CUSTOM_EMOJI,
            MAX_EDGE_PX,
            MAX_UPLOAD_BYTES,
            list_custom_emoji,
        )

        return {
            'emojis': list_custom_emoji(),
            'max_custom': MAX_CUSTOM_EMOJI,
            'limits': {
                'max_upload_bytes': MAX_UPLOAD_BYTES,
                'max_edge_px': MAX_EDGE_PX,
                'extensions': sorted(ALLOWED_EXT),
            },
        }

    def delete(self, slug: str, *, upload_folder: str | None = None) -> bool:
        from oneirodex.utils.custom_emoji import delete_custom_emoji, normalize_slug

        return delete_custom_emoji(normalize_slug(slug), upload_folder=upload_folder)

    def upload(self, *, slug: str, label: str, file, uploader, upload_folder: str | None):
        from oneirodex.utils.custom_emoji import upload_custom_emoji

        return upload_custom_emoji(
            slug=slug, label=label, file=file, uploader=uploader,
            upload_folder=upload_folder,
        )


def create_chat_emoji_router(
    flask_app,
    *,
    find_user: Callable[[int], Any | None],
    find_token: Callable[[str], Any | None],
    commit_token_touch: Callable[[Any], None],
    load_user_id: Callable[[str], Any | None] | None = None,
    login_manager: Any | None = None,
    data_access=None,
    database_scope: Callable[[Any], Any] | None = None,
) -> APIRouter:
    router = APIRouter()
    data = data_access or ChatEmojiData()

    @router.api_route('/api/chat/emoji', methods=['GET', 'HEAD'])
    def member_chat_emoji(request: Request):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            auth = request_auth_context(
                request, flask_app.config, find_user=find_user, find_token=find_token,
                commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                login_manager=login_manager,
            )
            if auth.user is None:
                response = _login_redirect(flask_app, request, login_manager, auth)
            elif auth.token is not None and not auth.has_scope('read:social'):
                from oneirodex.utils.api_contract import api_error_payload

                body, status = api_error_payload(
                    'Missing scope: read:social', code='forbidden',
                    detail={'required_scope': 'read:social'},
                )
                response = JSONResponse(body, status_code=status)
            else:
                try:
                    response = JSONResponse(data.member_read())
                except Exception:  # noqa: BLE001 — preserve a safe API failure
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload(
                        'Could not load chat emoji', code='internal',
                    )
                    response = JSONResponse(body, status_code=status)
            if auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            if request.method == 'HEAD':
                response.body = b''
            return response

    @router.api_route('/api/admin/chat-emoji', methods=['GET', 'HEAD'])
    @router.api_route('/api/admin/chat-emoji/{slug}', methods=['DELETE'])
    def chat_emoji(request: Request, slug: str | None = None):
        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            csrf_response = None
            if request.method == 'DELETE':
                from .csrf_compat import csrf_error_response
                from .request_auth import _lifetime_seconds
                from .session_compat import load_session_cookie

                cookie_name = str(flask_app.config.get('SESSION_COOKIE_NAME') or 'session')
                session_data = load_session_cookie(
                    request.cookies.get(cookie_name),
                    flask_app.config.get('SECRET_KEY'),
                    max_age=_lifetime_seconds(
                        flask_app.config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)
                    ),
                    fallback_secret_keys=flask_app.config.get('SECRET_KEY_FALLBACKS') or (),
                )
                csrf_response = csrf_error_response(request, session_data, flask_app.config)
            auth = None
            if csrf_response is None:
                auth = request_auth_context(
                    request,
                    flask_app.config,
                    find_user=find_user,
                    find_token=find_token,
                    commit_token_touch=commit_token_touch,
                    load_user_id=load_user_id,
                    login_manager=login_manager,
                )
            from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
            from oneirodex.utils.role_catalog import normalize_role

            if csrf_response is not None:
                response = csrf_response
            else:
                assert auth is not None
                user = auth.user
                is_admin = (
                    user is not None
                    and bool(getattr(user, 'is_authenticated', True))
                    and normalize_role(getattr(user, 'role', None) or '') == 'admin'
                )
                if user is None:
                    response = _login_redirect(
                        flask_app,
                        request,
                        login_manager,
                        auth,
                        message=getattr(login_manager, 'login_message', None),
                        category=getattr(login_manager, 'login_message_category', 'message'),
                        include_next=True,
                    )
                elif not is_admin:
                    response = _login_redirect(
                        flask_app,
                        request,
                        login_manager,
                        auth,
                        message='You must be an admin to access this page.',
                        category='danger',
                        include_next=False,
                    )
                elif auth.token is not None and not auth.has_scope('admin'):
                    payload, status = api_error_payload(
                        'This token does not have the admin scope', code='forbidden'
                    )
                    response = JSONResponse(payload, status_code=status)
                elif request.method == 'DELETE':
                    try:
                        if not data.delete(
                            slug or '', upload_folder=flask_app.config.get('UPLOAD_FOLDER'),
                        ):
                            payload, status = api_error_payload(
                                'Custom emoji not found', code='not_found'
                            )
                            response = JSONResponse(payload, status_code=status)
                        else:
                            response = JSONResponse(api_ok_payload(
                                {'message': 'Custom emoji deleted.'}
                            ))
                    except ValueError:
                        payload, status = api_error_payload(
                            'Invalid emoji slug', code='bad_request'
                        )
                        response = JSONResponse(payload, status_code=status)
                    except Exception:
                        from oneirodex.runtime_native.db_session import native_db as db
                        import logging

                        db.session.rollback()
                        logging.getLogger(__name__).warning('Custom emoji deletion failed')
                        payload, status = api_error_payload(
                            'Could not delete custom emoji', code='internal'
                        )
                        response = JSONResponse(payload, status_code=status)
                else:
                    try:
                        response = JSONResponse(api_ok_payload(data.read()))
                    except Exception:
                        logger = getattr(flask_app, 'logger', None)
                        if logger:
                            logger.warning('Could not load custom chat emoji')
                        payload, status = api_error_payload(
                            'Could not load custom chat emoji', code='internal'
                        )
                        response = JSONResponse(payload, status_code=status)

        from oneirodex.utils.security_headers import security_header_values

        response.headers.setdefault('Cache-Control', 'no-store')
        for key, value in security_header_values(flask_app.config).items():
            response.headers.setdefault(key, value)
        if request.method == 'HEAD':
            response.body = b''
        return response

    @router.post('/api/admin/chat-emoji')
    async def chat_emoji_upload(request: Request):
        from io import BytesIO

        from starlette.datastructures import UploadFile as StarletteUploadFile
        from werkzeug.datastructures import FileStorage

        from .csrf_compat import csrf_error_response
        from .request_auth import _lifetime_seconds
        from .session_compat import load_session_cookie
        from oneirodex.utils.custom_emoji import MAX_UPLOAD_BYTES
        from oneirodex.utils.api_contract import api_error_payload, api_ok_payload
        from oneirodex.utils.role_catalog import normalize_role

        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            cookie_name = str(flask_app.config.get('SESSION_COOKIE_NAME') or 'session')
            session_data = load_session_cookie(
                request.cookies.get(cookie_name), flask_app.config.get('SECRET_KEY'),
                max_age=_lifetime_seconds(
                    flask_app.config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)
                ),
                fallback_secret_keys=flask_app.config.get('SECRET_KEY_FALLBACKS') or (),
            )
            response = csrf_error_response(request, session_data, flask_app.config)
            auth = None
            if response is None:
                auth = request_auth_context(
                    request, flask_app.config, find_user=find_user, find_token=find_token,
                    commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                    login_manager=login_manager,
                )
                user = auth.user
                if user is None:
                    response = _login_redirect(
                        flask_app, request, login_manager, auth,
                        message=getattr(login_manager, 'login_message', None),
                        category=getattr(login_manager, 'login_message_category', 'message'),
                        include_next=True,
                    )
                elif normalize_role(getattr(user, 'role', None) or '') != 'admin':
                    response = _login_redirect(
                        flask_app, request, login_manager, auth,
                        message='You must be an admin to access this page.',
                        category='danger', include_next=False,
                    )
                elif auth.token is not None and not auth.has_scope('admin'):
                    body, status = api_error_payload(
                        'This token does not have the admin scope', code='forbidden',
                    )
                    response = JSONResponse(body, status_code=status)
            if response is None:
                form = await request.form()
                try:
                    upload = form.get('file')
                    file = None
                    if isinstance(upload, StarletteUploadFile):
                        raw = await upload.read(MAX_UPLOAD_BYTES + 1)
                        file = FileStorage(
                            stream=BytesIO(raw), filename=upload.filename,
                            content_type=upload.content_type,
                        )
                    slug = str(form.get('slug') or '')
                    label = str(form.get('label') or '')
                finally:
                    await form.close()
                try:
                    row = data.upload(
                        slug=slug, label=label, file=file, uploader=auth.user,
                        upload_folder=flask_app.config.get('UPLOAD_FOLDER'),
                    )
                    response = JSONResponse(api_ok_payload({
                        'emoji': row.to_dict(), 'message': 'Custom emoji uploaded.',
                    }), status_code=201)
                except ValueError as exc:
                    message = str(exc)
                    if message.startswith('Invalid image:'):
                        message = 'The file could not be read as an image'
                    body, status = api_error_payload(message, code='bad_request')
                    response = JSONResponse(body, status_code=status)
                except Exception:  # noqa: BLE001 — keep storage detail private
                    from oneirodex.runtime_native.db_session import native_db as db

                    db.session.rollback()
                    logger = getattr(flask_app, 'logger', None)
                    if logger:
                        logger.warning('Custom emoji upload failed')
                    body, status = api_error_payload(
                        'Could not upload custom emoji', code='internal',
                    )
                    response = JSONResponse(body, status_code=status)
            if auth is not None and auth.should_set_session_cookie:
                from .oidc_status import _set_session_cookie

                _set_session_cookie(response, flask_app, auth)
            from oneirodex.utils.security_headers import security_header_values

            response.headers.setdefault('Cache-Control', 'no-store')
            for key, value in security_header_values(flask_app.config).items():
                response.headers.setdefault(key, value)
            return response

    @router.post('/admin/chat_emoji')
    async def legacy_admin_chat_emoji(request: Request):
        from io import BytesIO

        from starlette.datastructures import UploadFile as StarletteUploadFile
        from werkzeug.datastructures import FileStorage

        from .csrf_compat import csrf_error_response
        from .request_auth import _lifetime_seconds
        from .session_compat import load_session_cookie
        from .oidc_status import _set_session_cookie
        from oneirodex.utils.custom_emoji import MAX_UPLOAD_BYTES
        from oneirodex.utils.role_catalog import normalize_role

        scope = database_scope(flask_app) if database_scope else nullcontext()
        with scope:
            form = None
            try:
                cookie_name = str(flask_app.config.get('SESSION_COOKIE_NAME') or 'session')
                session_data = load_session_cookie(
                    request.cookies.get(cookie_name), flask_app.config.get('SECRET_KEY'),
                    max_age=_lifetime_seconds(
                        flask_app.config.get('PERMANENT_SESSION_LIFETIME', 31_536_000)
                    ),
                    fallback_secret_keys=flask_app.config.get('SECRET_KEY_FALLBACKS') or (),
                )
                auth = request_auth_context(
                    request, flask_app.config, find_user=find_user, find_token=find_token,
                    commit_token_touch=commit_token_touch, load_user_id=load_user_id,
                    login_manager=login_manager,
                )
                user = auth.user
                response = None
                if user is None:
                    response = _login_redirect(
                        flask_app, request, login_manager, auth,
                        message=getattr(login_manager, 'login_message', None),
                        category=getattr(login_manager, 'login_message_category', 'message'),
                        include_next=True,
                    )
                elif normalize_role(getattr(user, 'role', None) or '') != 'admin':
                    response = _login_redirect(
                        flask_app, request, login_manager, auth,
                        message='You must be an admin to access this page.',
                        category='danger', include_next=False,
                    )
                elif auth.token is not None and not auth.has_scope('admin'):
                    from oneirodex.utils.api_contract import api_error_payload

                    body, status = api_error_payload(
                        'This token does not have the admin scope', code='forbidden',
                    )
                    response = JSONResponse(body, status_code=status)
                if response is None:
                    from .bounded_multipart import (
                        InvalidContentLength, RequestBodyTooLarge,
                        bounded_multipart_form,
                    )

                    try:
                        form = await bounded_multipart_form(
                            request, max_body_bytes=MAX_UPLOAD_BYTES + 64 * 1024,
                            max_files=1, max_fields=12, max_part_size=64 * 1024,
                        )
                    except RequestBodyTooLarge:
                        from oneirodex.utils.api_contract import api_error_payload

                        body, status = api_error_payload(
                            'Emoji upload exceeds the size limit.', code='payload_too_large',
                        )
                        response = JSONResponse(body, status_code=status)
                    except InvalidContentLength:
                        from oneirodex.utils.api_contract import api_error_payload

                        body, status = api_error_payload(
                            'Invalid request size.', code='bad_request',
                        )
                        response = JSONResponse(body, status_code=status)
                    except Exception:
                        from oneirodex.utils.api_contract import api_error_payload

                        body, status = api_error_payload(
                            'Invalid multipart form data.', code='bad_request',
                        )
                        response = JSONResponse(body, status_code=status)
                if response is None:
                    response = csrf_error_response(
                        request, session_data, flask_app.config,
                        token=str(form.get('csrf_token') or ''),
                    )
                if response is None:
                    action = str(form.get('action') or 'upload').strip()
                    if action == 'delete':
                        slug = str(form.get('slug') or '')
                        try:
                            deleted = data.delete(
                                slug, upload_folder=flask_app.config.get('UPLOAD_FOLDER'),
                            )
                            message = f'Deleted :{slug}:' if deleted else 'Emoji not found'
                            category = 'success' if deleted else 'error'
                        except ValueError:
                            message, category = 'Invalid emoji slug', 'error'
                    else:
                        upload = form.get('file')
                        file = None
                        if isinstance(upload, StarletteUploadFile):
                            raw = await upload.read(MAX_UPLOAD_BYTES + 1)
                            file = FileStorage(
                                stream=BytesIO(raw), filename=upload.filename,
                                content_type=upload.content_type,
                            )
                        try:
                            row = data.upload(
                                slug=str(form.get('slug') or ''),
                                label=str(form.get('label') or ''), file=file,
                                uploader=auth.user,
                                upload_folder=flask_app.config.get('UPLOAD_FOLDER'),
                            )
                            message, category = f'Uploaded {row.reaction_key()}', 'success'
                        except ValueError as exc:
                            message, category = str(exc), 'error'
                        except Exception:
                            from oneirodex.runtime_native.db_session import native_db as db

                            db.session.rollback()
                            logger = getattr(flask_app, 'logger', None)
                            if logger:
                                logger.warning('Custom emoji upload failed')
                            message, category = 'Could not upload custom emoji', 'error'
                    flashes = list(auth.session_data.get('_flashes') or [])
                    flashes.append((category, message))
                    auth.session_data['_flashes'] = flashes
                    response = RedirectResponse('/admin/chat_emoji', status_code=302)
                    _set_session_cookie(response, flask_app, auth)
                return response
            finally:
                if form is not None:
                    await form.close()

    return router


def mount_chat_emoji_routes(app: FastAPI, flask_app, **kwargs):
    app.include_router(create_chat_emoji_router(flask_app, **kwargs))
    return app
