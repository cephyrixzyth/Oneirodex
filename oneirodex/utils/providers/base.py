"""Base types for metadata image providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass

import requests

from oneirodex.utils.http_safe import (
    MAX_OUTBOUND_IMAGE_BYTES,
    read_response_limited,
    safe_get,
)
from oneirodex.utils.security import validate_user_outbound_http_url


@dataclass(frozen=True)
class ImageSearchResult:
    """Normalized artwork search hit from an external provider."""

    id: str
    url: str
    thumb_url: str | None = None
    width: int | None = None
    height: int | None = None
    score: int | None = None
    style: str | None = None
    mime: str | None = None
    nsfw: bool | None = None
    game_id: int | None = None
    game_name: str | None = None
    image_type: str = 'grid'

    def to_dict(self) -> dict:
        return asdict(self)


class ProviderDisabledError(Exception):
    """Raised when a provider is not configured or enabled."""

    def __init__(self, provider_id: str, message: str):
        self.provider_id = provider_id
        self.message = message
        super().__init__(message)


class MetadataImageProvider(ABC):
    """Artwork-only provider — fetches cover/grid images, never game binaries."""

    id: str
    name: str
    description: str

    @abstractmethod
    def is_enabled(self) -> bool:
        """Return True when credentials/configuration are present."""

    @abstractmethod
    def search_covers(self, query: str, *, limit: int = 20) -> list[ImageSearchResult]:
        """Search provider artwork by game title."""

    @abstractmethod
    def fetch_image(self, url: str) -> tuple[bytes, str | None]:
        """Download image bytes and optional content type from a provider URL."""

    def config_hint(self) -> str:
        """Human-readable hint for enabling this provider."""
        return 'Configure provider credentials in environment or Admin settings.'


def fetch_outbound_image(
    url: str,
    *,
    timeout: int,
    headers: dict | None = None,
) -> tuple[bytes, str | None]:
    """Download cover bytes through the same SSRF gate as ``download_image``.

    Provider ``fetch_image`` used to call ``requests.get`` on the URL as given,
    so a 302 from a valid CDN to a loopback host walked past the validator.
    """
    if not (url or '').startswith(('http://', 'https://')):
        raise ValueError('Image URL must be absolute http(s)')
    ok, result = validate_user_outbound_http_url(url)
    if not ok:
        raise ValueError(f'Blocked outbound URL: {result}')
    # A caller-owned session is required for stream=True: safe_request's
    # temporary pinned-TLS session eagerly reads response.content before close.
    with requests.Session() as session:
        response = safe_get(
            result,
            validator=validate_user_outbound_http_url,
            timeout=timeout,
            headers=headers,
            session=session,
            stream=True,
        )
        try:
            if response.status_code != 200:
                raise RuntimeError(f'Failed to download image ({response.status_code})')
            content_type = response.headers.get('Content-Type')
            data = read_response_limited(response, MAX_OUTBOUND_IMAGE_BYTES)
            return data, content_type
        finally:
            close = getattr(response, 'close', None)
            if callable(close):
                close()


def mask_api_key(key: str | None) -> str | None:
    """Return a masked preview of an API key for admin status displays."""
    if not key:
        return None
    trimmed = key.strip()
    if len(trimmed) <= 8:
        return '****'
    return f'{trimmed[:4]}...{trimmed[-4:]}'
