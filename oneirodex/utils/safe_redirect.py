"""Same-site redirect targets for ``?next=`` style parameters."""
from __future__ import annotations

from urllib.parse import urlsplit

DEFAULT_LANDING = '/discover'


def safe_next_url(candidate: object, fallback: str = DEFAULT_LANDING) -> str:
    """Return ``candidate`` when it is a same-site path, otherwise ``fallback``.

    Refuses absolute and protocol-relative URLs, the ``/\\host`` form browsers
    normalise to ``//host``, and control characters, which browsers strip
    (so ``/\\t/host`` would also become ``//host``).
    """
    if not isinstance(candidate, str):
        return fallback
    value = candidate.strip()
    if not value.startswith('/') or value[1:2] in ('/', '\\'):
        return fallback
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        return fallback
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        return fallback
    return value
