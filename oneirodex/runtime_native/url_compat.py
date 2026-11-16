"""URL normalization helpers for behavior that mirrors the legacy Flask stack."""

from werkzeug.urls import uri_to_iri


def request_url_iri(request) -> str:
    """Return the request URL in Werkzeug's IRI form.

    Starlette preserves URI escapes in ``Request.url`` while Werkzeug decodes
    valid escapes in the URL parts it exposes. Flask-Login uses the Werkzeug
    representation when it builds the ``next`` query parameter.
    """
    return uri_to_iri(str(request.url))
