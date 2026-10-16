from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from flask import Flask

from oneirodex.runtime_native.openapi_documents import create_openapi_documents_router


def _client(tmp_path):
    root = tmp_path / 'oneirodex'
    docs = tmp_path / 'docs' / 'openapi'
    docs.mkdir(parents=True)
    root.mkdir()
    (docs / 'openapi.json').write_text('{"openapi":"3.1.0"}\n', encoding='utf-8')
    (docs / 'openapi.yaml').write_text('openapi: 3.1.0\n', encoding='utf-8')
    flask_app = Flask(__name__)
    flask_app.root_path = str(root)
    flask_app.config.update(SECRET_KEY='native-openapi-docs', CSP_ENABLED=False)
    app = FastAPI()
    app.include_router(create_openapi_documents_router(flask_app))
    return TestClient(app), docs


def test_public_openapi_documents_keep_files_and_media_types(tmp_path):
    client, docs = _client(tmp_path)
    json_doc = client.get('/api/openapi.json')
    yaml_doc = client.get('/api/openapi.yaml')
    head = client.head('/api/openapi.json')

    assert json_doc.status_code == 200
    assert json_doc.json() == {'openapi': '3.1.0'}
    assert json_doc.headers['content-type'].startswith('application/json')
    assert yaml_doc.status_code == 200
    assert yaml_doc.content == (docs / 'openapi.yaml').read_bytes()
    assert yaml_doc.headers['content-type'].startswith('application/yaml')
    assert head.status_code == 200 and head.content == b''
    assert head.headers['content-length'] == str(len(json_doc.content))


def test_missing_openapi_document_keeps_safe_not_found_envelope(tmp_path):
    client, docs = _client(tmp_path)
    (docs / 'openapi.yaml').unlink()
    response = client.get('/api/openapi.yaml')
    assert response.status_code == 404
    assert response.json()['error_code'] == 'not_found'
