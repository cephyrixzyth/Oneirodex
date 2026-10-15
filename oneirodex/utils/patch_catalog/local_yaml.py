"""Local YAML/JSON patch catalog — operator-owned file only."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from oneirodex.utils.patch_catalog.base import PatchCatalogHit, PatchCatalogProvider

_WS = re.compile(r'[^a-z0-9]+')


def normalize_title(value: str | None) -> str:
    raw = (value or '').strip().lower()
    return _WS.sub(' ', raw).strip()


def load_catalog_file(path: str) -> dict[str, Any]:
    """Load JSON or YAML catalog; raises ValueError on bad input."""
    if not path or not os.path.isfile(path):
        raise ValueError(f'Catalog file not found: {path or "(empty)"}')
    with open(path, 'r', encoding='utf-8') as fh:
        text = fh.read()
    lower = path.lower()
    if lower.endswith(('.yaml', '.yml')):
        try:
            import yaml  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise ValueError('PyYAML required to read YAML catalogs') from exc
        data = yaml.safe_load(text) or {}
    else:
        data = json.loads(text or '{}')
    if not isinstance(data, dict):
        raise ValueError('Catalog root must be an object')
    entries = data.get('entries')
    if entries is None:
        entries = []
    if not isinstance(entries, list):
        raise ValueError('Catalog entries must be a list')
    return {'version': data.get('version', 1), 'entries': entries}


def score_entry(query_norm: str, entry: dict[str, Any]) -> int:
    """Higher is better; 0 means no match."""
    if not query_norm:
        return 0
    titles = [entry.get('title') or '']
    aliases = entry.get('title_aliases') or []
    if isinstance(aliases, str):
        aliases = [aliases]
    titles.extend(aliases)
    best = 0
    for title in titles:
        norm = normalize_title(str(title))
        if not norm:
            continue
        if norm == query_norm:
            best = max(best, 100)
        elif query_norm in norm or norm in query_norm:
            best = max(best, 70)
        else:
            q_parts = set(query_norm.split())
            t_parts = set(norm.split())
            if q_parts and q_parts <= t_parts:
                best = max(best, 50)
    return best


def entry_to_hit(entry: dict[str, Any], *, provider_id: str, score: int, index: int) -> PatchCatalogHit:
    title = str(entry.get('title') or 'Untitled').strip() or 'Untitled'
    source = str(entry.get('source_url') or '').strip()
    return PatchCatalogHit(
        id=f'{provider_id}:{index}:{normalize_title(title)[:40]}',
        title=title,
        source_url=source,
        provider=provider_id,
        platform=(str(entry['platform']).strip() if entry.get('platform') else None),
        region=(str(entry['region']).strip() if entry.get('region') else None),
        target_language=(
            str(entry['target_language']).strip() if entry.get('target_language') else None
        ),
        patch_format=(str(entry['patch_format']).strip() if entry.get('patch_format') else None),
        notes=(str(entry['notes']).strip() if entry.get('notes') else None),
        score=score,
    )


class LocalYamlPatchCatalogProvider(PatchCatalogProvider):
    """Reads PATCH_CATALOG_PATH when ENABLE_PATCH_CATALOG is on."""

    id = 'local_yaml'
    name = 'Local catalog (YAML/JSON)'
    description = 'Operator-owned patch guide catalog from PATCH_CATALOG_PATH (metadata only).'

    def is_enabled(self) -> bool:
        try:
            from flask import current_app

            enabled = str(current_app.config.get('ENABLE_PATCH_CATALOG', '')).lower() in (
                '1',
                'true',
                'yes',
                'on',
            )
            path = (current_app.config.get('PATCH_CATALOG_PATH') or '').strip()
            return enabled and bool(path) and os.path.isfile(path)
        except (ImportError, RuntimeError):
            enabled = os.getenv('ENABLE_PATCH_CATALOG', 'true').lower() in (
                '1',
                'true',
                'yes',
                'on',
            )
            path = (os.getenv('PATCH_CATALOG_PATH') or '').strip()
            return enabled and bool(path) and os.path.isfile(path)

    def _catalog_path(self) -> str:
        try:
            from flask import current_app

            return (current_app.config.get('PATCH_CATALOG_PATH') or '').strip()
        except (ImportError, RuntimeError):
            return (os.getenv('PATCH_CATALOG_PATH') or '').strip()

    def search(
        self,
        query: str,
        *,
        platform: str | None = None,
        region: str | None = None,
        target_lang: str | None = None,
        limit: int = 20,
    ) -> list[PatchCatalogHit]:
        if not self.is_enabled():
            return []
        path = self._catalog_path()
        try:
            data = load_catalog_file(path)
        except (OSError, ValueError, json.JSONDecodeError):
            return []

        q_norm = normalize_title(query)
        plat = (platform or '').strip().upper() or None
        reg = (region or '').strip().upper() or None
        lang = (target_lang or '').strip().lower() or None

        hits: list[PatchCatalogHit] = []
        for index, entry in enumerate(data['entries']):
            if not isinstance(entry, dict):
                continue
            score = score_entry(q_norm, entry)
            if score <= 0:
                continue
            if plat and entry.get('platform'):
                if str(entry['platform']).strip().upper() != plat:
                    continue
            if reg and entry.get('region'):
                if str(entry['region']).strip().upper() != reg:
                    continue
            if lang and entry.get('target_language'):
                if str(entry['target_language']).strip().lower() != lang:
                    continue
            if not str(entry.get('source_url') or '').strip():
                continue
            hits.append(entry_to_hit(entry, provider_id=self.id, score=score, index=index))

        hits.sort(key=lambda h: (-h.score, h.title.lower()))
        return hits[: max(1, min(int(limit or 20), 50))]

    def config_hint(self) -> str:
        return 'Set ENABLE_PATCH_CATALOG=true and PATCH_CATALOG_PATH to your YAML/JSON catalog file.'
