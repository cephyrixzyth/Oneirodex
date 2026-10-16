from __future__ import annotations

from types import SimpleNamespace

from flask import Flask

from oneirodex import cache
from oneirodex.runtime_native import filter_reads as native_filter_reads
from oneirodex.runtime_native.filter_reads import FilterReadData


def test_filter_bundle_data_uses_explicit_static_url_without_flask_context(monkeypatch):
    flask_app = Flask(__name__)
    flask_app.config.update(APPLICATION_ROOT='/household')
    flask_app.app_context = lambda: (_ for _ in ()).throw(
        AssertionError('filter data adapter pushed a Flask app context')
    )
    monkeypatch.setattr(cache, 'get', lambda _key: None)
    monkeypatch.setattr(cache, 'set', lambda *_args, **_kwargs: None)

    fallback_urls = []
    monkeypatch.setattr(
        'oneirodex.utils.filter_catalog.libraries_payload',
        lambda _user, *, fallback_image_url=None: fallback_urls.append(fallback_image_url) or [],
    )
    monkeypatch.setattr(
        'oneirodex.utils.filter_catalog.library_platforms_payload',
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr('oneirodex.utils.filter_catalog.igdb_platforms_payload', lambda: [])
    monkeypatch.setattr('oneirodex.utils.filter_catalog.taxonomy_list', lambda _model: [])
    monkeypatch.setattr('oneirodex.utils.filter_catalog.ownership_store_options', lambda: [])

    payload = FilterReadData(flask_app).bundle(SimpleNamespace(id=44))

    assert payload['libraries'] == []
    assert fallback_urls == ['/household/static/newstyle/default_library.jpg']


def test_filter_api_errors_use_framework_independent_envelopes():
    response = native_filter_reads._api_error(
        'Database error retrieving filters', 'internal'
    )

    assert response.status_code == 500
    assert response.body
