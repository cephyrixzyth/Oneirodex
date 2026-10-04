"""Read-only mod catalogue sources (INSP-22, v11 cycle H2b).

A *catalogue source* answers one question -- *which community mods exist for
this game?* -- from a public registry, and hands back :class:`ModHit` rows a
librarian can add to the game's tracked mod list. Every hit is metadata and
a deep link: the name, a version, the loader it needs, the registry page.

What a source never does:

* **download** -- the only file movement in the mods story stays the
  companion's BYO ``source_url`` staging, which the librarian chose row by
  row. A catalogue hit fills ``source_url`` with the *registry page*, not an
  archive.
* **write** -- nothing here touches the pack; the member panel's *Add to
  list* does, through the same validated ``POST`` any librarian uses.
* **guess silently** -- a source that is off, unreachable or mid-schema-change
  returns ``None`` (*no data*), which the API reports as ``unavailable``.
  An empty list means the registry answered and had nothing.

Registries in API-quality order, per the harvest register: Thunderstore
(open REST, no key) -> Modrinth (open, no key; asks for a User-Agent) ->
GameBanana and Nexus in H2c -> CurseForge declined on its ToS.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any

from flask import current_app, has_app_context

TIMEOUT_SECONDS = 10
USER_AGENT = 'Oneirodex/1.0 (+https://github.com/cephyrixzyth/Oneirodex; mod catalogue, read-only)'
DEFAULT_LIMIT = 20
MAX_LIMIT = 50


@dataclass
class ModHit:
    name: str
    url: str
    source: str
    version: str = ''
    loader: str = ''
    summary: str = ''
    author: str = ''
    downloads: int | None = None
    updated: str | None = None
    categories: list[str] = field(default_factory=list)
    # INSP-38 -- names of packages this one needs, when the registry says so.
    dependencies: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _truthy(raw: str | None, default: bool) -> bool:
    text = (raw or '').strip().lower()
    if not text:
        return default
    return text in ('1', 'true', 'yes', 'on')


def _testing() -> bool:
    try:
        return bool(has_app_context() and current_app.config.get('TESTING'))
    except Exception:  # noqa: BLE001
        return False


def catalog_enabled() -> bool:
    """``ENABLE_MOD_CATALOG`` (default on); off under pytest unless
    ``MOD_CATALOG_IN_TESTS=1`` so a mocked transport can be exercised."""
    if not _truthy(os.environ.get('ENABLE_MOD_CATALOG'), True):
        return False
    if _testing() and not _truthy(os.environ.get('MOD_CATALOG_IN_TESTS'), False):
        return False
    return True


def clamp_limit(raw: Any) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    return max(1, min(value, MAX_LIMIT))


def as_int(raw: Any) -> int | None:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def text(raw: Any, limit: int = 500) -> str:
    return str(raw or '').strip()[:limit]
