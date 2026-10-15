"""FastAPI delivery for the public, checked-in OpenAPI documents."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, FastAPI
from starlette.responses import FileResponse, JSONResponse


def create_openapi_documents_router(flask_app) -> APIRouter:
    router = APIRouter()
    documents = Path(flask_app.root_path).resolve().parent / 'docs' / 'openapi'

    @router.api_route('/api/openapi.json', methods=['GET', 'HEAD'])
    async def openapi_json():
        return _document_response(
            documents / 'openapi.json', 'application/json', flask_app.config,
        )

    @router.api_route('/api/openapi.yaml', methods=['GET', 'HEAD'])
    async def openapi_yaml():
        return _document_response(
            documents / 'openapi.yaml', 'application/yaml', flask_app.config,
        )

    return router


def _document_response(path: Path, media_type: str, config):
    if not path.is_file():
        from oneirodex.utils.api_contract import api_error_payload
        payload, status = api_error_payload('OpenAPI document not found', code='not_found')
        response = JSONResponse(payload, status_code=status)
    else:
        response = FileResponse(path, media_type=media_type)
    from oneirodex.utils.security_headers import security_header_values
    for key, value in security_header_values(config).items():
        response.headers.setdefault(key, value)
    return response


def mount_openapi_documents_routes(app: FastAPI, flask_app):
    app.include_router(create_openapi_documents_router(flask_app))
    return app
