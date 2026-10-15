"""Framework-independent locale values and normalization."""

from __future__ import annotations

SUPPORTED_LOCALES = ('en', 'es')
DEFAULT_LOCALE = 'en'


def normalize_locale(value: str | None) -> str:
    if not value:
        return DEFAULT_LOCALE
    code = str(value).strip().lower().replace('_', '-')
    if code in SUPPORTED_LOCALES:
        return code
    short = code.split('-', 1)[0]
    if short in SUPPORTED_LOCALES:
        return short
    return DEFAULT_LOCALE
