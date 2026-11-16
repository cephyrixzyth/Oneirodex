"""Flask MultiDict-compatible accessors for native form data."""
from __future__ import annotations


def first_form_values(fields):
    """Collapse parsed URL-encoded fields using Flask MultiDict first-value semantics."""
    return {name: values[0] for name, values in fields.items() if values}


def first_form_value(form, key, default=None):
    """Match Flask ``request.form.get()``, which selects the first repeated value.

    Ordinary mappings keep their normal ``get`` behavior. Starlette FormData and
    Werkzeug MultiDict expose ``getlist`` and use the first submitted value here.
    """
    getlist = getattr(form, 'getlist', None)
    if callable(getlist):
        values = [value for value in getlist(key) if not _is_upload(value)]
        return values[0] if values else default
    return form.get(key, default)


def form_uploads(form, key):
    """Match Flask ``request.files.getlist()`` for Starlette multipart data.

    Starlette FormData combines text fields and uploaded files in one list;
    Flask keeps those in separate ``request.form`` and ``request.files`` maps.
    """
    getlist = getattr(form, 'getlist', None)
    if not callable(getlist):
        return []
    return [value for value in getlist(key) if _is_upload(value)]


def first_form_upload(form, key, default=None):
    """Return the first uploaded file for a key, matching Flask ``request.files``."""
    uploads = form_uploads(form, key)
    return uploads[0] if uploads else default


def _is_upload(value):
    """Recognize Starlette UploadFile and Werkzeug FileStorage values."""
    return isinstance(getattr(value, 'filename', None), str) and callable(getattr(value, 'read', None))
