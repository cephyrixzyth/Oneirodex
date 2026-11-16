from __future__ import annotations

from pathlib import Path
import re
from io import BytesIO

from starlette.datastructures import FormData, QueryParams, UploadFile
from werkzeug.datastructures import MultiDict

from oneirodex.runtime_native.form_compat import first_form_upload, first_form_value, form_uploads
from oneirodex.runtime_native.query_compat import first_query_value


def test_first_query_value_matches_flask_repeated_key_selection():
    params = QueryParams('limit=5&limit=2')

    assert first_query_value(params, 'limit') == '5'
    assert first_query_value(params, 'missing') is None
    assert first_query_value(params, 'missing', 'fallback') == 'fallback'


def test_native_routes_do_not_call_starlette_query_params_get_directly():
    runtime_native = Path(__file__).resolve().parents[1] / 'oneirodex' / 'runtime_native'
    direct_get_calls = [
        path.relative_to(runtime_native).as_posix()
        for path in runtime_native.glob('*.py')
        if 'request.query_params.get(' in path.read_text(encoding='utf-8')
    ]

    assert direct_get_calls == []


def test_first_form_value_matches_flask_repeated_field_selection():
    form = FormData([('status', 'first'), ('status', 'last')])
    flask_form = MultiDict([('status', 'first'), ('status', 'last')])

    assert first_form_value(form, 'status') == 'first'
    assert first_form_value(form, 'status') == flask_form.get('status')
    assert first_form_value(flask_form, 'status') == flask_form.get('status')
    assert first_form_value(form, 'missing', 'fallback') == 'fallback'
    assert form.getlist('status') == ['first', 'last']


def test_form_uploads_matches_flask_files_multidict_selection():
    upload = UploadFile(BytesIO(b'fixture'), filename='invalid.txt')
    form = FormData([('files', 'text-field'), ('files', upload)])

    assert form_uploads(form, 'files') == [upload]
    assert form.getlist('files') == ['text-field', upload]
    assert form_uploads({'files': 'text-field'}, 'files') == []
    assert first_form_value({'status': 'mapping'}, 'status') == 'mapping'
    assert first_form_value({}, 'missing', 'fallback') == 'fallback'


def test_form_values_and_uploads_are_separated_like_flask_request_maps():
    upload_first = UploadFile(BytesIO(b'first'), filename='first.txt')
    text_first = FormData([('value', 'text'), ('value', upload_first)])
    assert first_form_value(text_first, 'value') == 'text'
    assert first_form_upload(text_first, 'value') is upload_first

    upload_before_text = UploadFile(BytesIO(b'first'), filename='first.txt')
    file_first = FormData([('value', upload_before_text), ('value', 'text')])
    assert first_form_value(file_first, 'value') == 'text'
    assert first_form_upload(file_first, 'value') is upload_before_text
    assert first_form_upload(file_first, 'missing', 'fallback') == 'fallback'


def test_native_routes_do_not_call_form_get_directly():
    runtime_native = Path(__file__).resolve().parents[1] / 'oneirodex' / 'runtime_native'
    direct_form_get_calls = [
        path.relative_to(runtime_native).as_posix()
        for path in runtime_native.glob('*.py')
        if path.name != 'form_compat.py'
        and re.search(r'(?<![A-Za-z0-9_])(?:[A-Za-z_][A-Za-z0-9_]*form|form)\.get\(', path.read_text(encoding='utf-8'))
    ]

    assert direct_form_get_calls == []
