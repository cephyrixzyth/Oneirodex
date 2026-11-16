"""Conservative, mandatory redaction for external support text.

This is a diagnostic filter, not a guarantee that arbitrary prose is anonymous.
Keep the original local ticket; show the filtered payload before forwarding.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

REDACTED = '[REDACTED]'
_PRIVATE_KEY = re.compile(
    r'-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----.*?'
    r'(?:-----END (?:[A-Z0-9]+ )*PRIVATE KEY-----|\Z)', re.S,
)
_URL = re.compile(r'\b[a-z][a-z0-9+.-]*://[^\s<>"`]+', re.I)
_HEADER = re.compile(
    r'\b((?:proxy-)?authorization|(?:set-)?cookie)([ \t]*:[ \t]*)'
    r'[^\r\n]*(?:\r?\n[ \t]+[^\r\n]*)*', re.I,
)
_ASSIGNMENT = re.compile(
    r'''(?ix)
    (?P<key>["']?\b[a-z0-9_-]*
    (?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|credential|session[_-]?id|authorization|cookie)
    ["']?\s*[:=]\s*)
    (?:\[REDACTED\]|"(?:\\.|[^"\\])*(?:"|\Z)|'(?:\\.|[^'\\])*(?:'|\Z)|[^\s,;\]}]+)
    ''',
)
_BEARER = re.compile(r'\b(Bearer|Basic)\s+[A-Za-z0-9_./+=:-]+', re.I)
_TOKEN = re.compile(
    r'\b(?:gh[pousr]_|github_pat_|gt_|sk-(?:proj-|svcacct-)?)[A-Za-z0-9_-]{8,}'
    r'|\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b',
)
_EMAIL = re.compile(r'[A-Z0-9.!#$%&\'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}', re.I)
_HOME = re.compile(
    r'''(?ix)(?:[a-z]:[\\/]+Users[\\/]+|/(?:home|Users)/)[^\s<>"'`]+''',
)


def _redact_url(match: re.Match) -> str:
    raw = match.group()
    try:
        parts = urlsplit(raw)
        # Accessing these also validates malformed authority/port forms.
        if not parts.hostname:
            return REDACTED
        _ = parts.port
        authority = parts.netloc.rsplit('@', 1)[-1]
        # Query names/values and fragments can carry arbitrary or encoded secrets.
        # Drop them as a unit instead of guessing every provider's parameter names.
        return urlunsplit((parts.scheme, authority, parts.path,
                           'redacted' if parts.query else '',
                           'redacted' if parts.fragment else ''))
    except ValueError:
        return REDACTED


def redact_support_text(text: str, *, secrets: tuple[str, ...] = ()) -> str:
    """Filter every outbound representation before truncation/JSON serialization."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    text = _PRIVATE_KEY.sub(REDACTED, text)
    text = _URL.sub(_redact_url, text)
    text = _HEADER.sub(lambda m: m[1] + m[2] + REDACTED, text)
    text = _ASSIGNMENT.sub(lambda m: m['key'] + REDACTED, text)
    text = _BEARER.sub(lambda m: m[1] + ' ' + REDACTED, text)
    text = _TOKEN.sub(REDACTED, text)
    text = _EMAIL.sub(REDACTED, text)
    return _HOME.sub(REDACTED, text)
