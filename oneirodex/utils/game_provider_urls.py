"""Editable per-provider links for the game edit form.

The identify form can search six providers, but only IGDB's URL had a field —
a Steam or GOG page found while identifying a title had nowhere to go. These
are stored the same way scanning stores them, as `GameURL` rows keyed by
`url_type`, so nothing else that reads them has to change.
"""

from __future__ import annotations

from urllib.parse import urlparse

# Keys match the vocabulary `website_category_to_string` already writes, so a
# link IGDB filled in and one typed here are the same row. The last three have
# no IGDB category but are providers the form can search.
PROVIDER_URL_FIELDS: tuple[tuple[str, str], ...] = (
    ('steam', 'Steam'),
    ('gog', 'GOG'),
    ('epicgames', 'Epic Games'),
    ('itch', 'itch.io'),
    ('rawg', 'RAWG'),
    ('mobygames', 'MobyGames'),
    ('thegamesdb', 'TheGamesDB'),
    ('official', 'Official site'),
    ('wikipedia', 'Wikipedia'),
)

EDITABLE_KEYS = frozenset(key for key, _ in PROVIDER_URL_FIELDS)

FORM_PREFIX = 'provider_url_'


def is_http_url(value: str | None) -> bool:
    """Only http(s). Keeps `javascript:` and friends out of a rendered link."""
    if not value:
        return False
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return False
    return parsed.scheme in ('http', 'https') and bool(parsed.netloc)


def provider_url_fields(game, form_data=None) -> list[dict[str, str | None]]:
    """Rows for the template: one per provider, carrying any URL on file.

    `form_data` wins when given. A save that fails validation re-renders the
    form, and reading these back off the game would quietly discard whatever
    the member had just typed into them.
    """
    existing: dict[str, str] = {}
    for row in getattr(game, 'urls', None) or []:
        key = (getattr(row, 'url_type', None) or '').strip().lower()
        if key in EDITABLE_KEYS and key not in existing:
            existing[key] = getattr(row, 'url', '') or ''

    rows = []
    for key, label in PROVIDER_URL_FIELDS:
        field = f'{FORM_PREFIX}{key}'
        if form_data is not None and field in form_data:
            value = (form_data.get(field) or '').strip() or None
        else:
            value = existing.get(key)
        rows.append({'key': key, 'label': label, 'value': value})
    return rows


def apply_provider_urls(game, form_data) -> int:
    """Sync the editable provider rows to what the form submitted.

    Only the keys this form owns are touched — a `youtube` or patch-guide row
    written by something else has no field here and must survive the save.
    A field left blank removes that provider's row, which is the only way the
    form can express "this link was wrong".

    Returns the number of rows added or changed.
    """
    from oneirodex.runtime_native.db_session import native_db as db
    from oneirodex.models import GameURL

    changed = 0
    by_key: dict[str, list] = {}
    for row in list(getattr(game, 'urls', None) or []):
        key = (getattr(row, 'url_type', None) or '').strip().lower()
        if key in EDITABLE_KEYS:
            by_key.setdefault(key, []).append(row)

    for key, _label in PROVIDER_URL_FIELDS:
        submitted = (form_data.get(f'{FORM_PREFIX}{key}') or '').strip()
        rows = by_key.get(key, [])
        if submitted and not is_http_url(submitted):
            # Refusing beats storing something the details page would render
            # as a link. The field keeps whatever was already on file.
            continue
        if not submitted:
            for row in rows:
                db.session.delete(row)
                changed += 1
            continue
        if rows:
            if rows[0].url != submitted:
                rows[0].url = submitted
                changed += 1
            # Collapse any duplicates a previous import left behind.
            for extra in rows[1:]:
                db.session.delete(extra)
                changed += 1
        else:
            db.session.add(
                GameURL(game_uuid=game.uuid, url_type=key, url=submitted)
            )
            changed += 1

    return changed
