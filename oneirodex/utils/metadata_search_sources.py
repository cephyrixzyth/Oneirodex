"""Provider capability catalogue for admin metadata search."""


def build_metadata_search_sources() -> dict:
    from oneirodex.utils.providers.meta_quest import (
        get_meta_quest_api_mode,
        unofficial_graphql_enabled,
    )
    from oneirodex.utils.providers.mobygames import (
        get_mobygames_api_key,
        mobygames_config_hint,
    )
    from oneirodex.utils.providers.thegamesdb import (
        get_thegamesdb_api_key,
        thegamesdb_config_hint,
    )

    mode = get_meta_quest_api_mode()
    moby_key = bool(get_mobygames_api_key())
    tgdb_key = bool(get_thegamesdb_api_key())
    return {
        'sources': [
            {'id': 'steam', 'name': 'Steam', 'needs_key': False, 'ownership_only': False,
             'includes_software': True,
             'note': 'Includes Steam type=software by default; results carry item_kind.'},
            {'id': 'rawg', 'name': 'RAWG', 'needs_key': True, 'ownership_only': False},
            {'id': 'gog', 'name': 'GOG', 'needs_key': False, 'ownership_only': False},
            {'id': 'epic', 'name': 'Epic Games Store', 'needs_key': False, 'ownership_only': True},
            {'id': 'itch', 'name': 'itch.io', 'needs_key': False, 'ownership_only': False},
            {'id': 'giantbomb', 'name': 'GiantBomb', 'needs_key': True, 'ownership_only': False},
            {
                'id': 'mobygames',
                'name': 'MobyGames',
                'aliases': ['moby'],
                'needs_key': True,
                'key_configured': moby_key,
                'ownership_only': False,
                'config_hint': mobygames_config_hint(),
                'note': (
                    'Optional Class D catalog search (MOBYGAMES_API_KEY). '
                    'Empty results when unset — no 500. Manual identify only; '
                    'not Stage D auto-cascade. Metadata / cover URLs only.'
                ),
            },
            {
                'id': 'thegamesdb',
                'name': 'TheGamesDB',
                'aliases': ['tgdb'],
                'needs_key': True,
                'key_configured': tgdb_key,
                'ownership_only': False,
                'config_hint': thegamesdb_config_hint(),
                'note': (
                    'Optional Class D catalog search (THEGAMESDB_API_KEY) — '
                    'console leaf identify / covers. Empty results when unset — no 500. '
                    'Manual identify only; not Stage D auto-cascade. Metadata / cover URLs only.'
                ),
            },
            {
                'id': 'meta_quest',
                'name': 'Meta Quest Store',
                'aliases': ['meta', 'quest'],
                'needs_key': False,
                'needs_igdb': mode == 'igdb',
                'ownership_only': True,
                'api_mode': mode,
                'api_modes': ['igdb', 'csv_only', 'disabled', 'unofficial_graphql'],
                'unofficial_graphql': unofficial_graphql_enabled(),
                'note': (
                    'Identify via IGDB Quest platforms by default (META_QUEST_API_MODE=igdb). '
                    'Ownership: CSV register-only (POST /api/ownership/meta_quest/csv). '
                    'Unofficial GraphQL is off unless META_QUEST_UNOFFICIAL_GRAPHQL=1. '
                    'Never downloads DRM titles. VR stays is_vr / Virtual Reality perspective.'
                ),
            },
        ],
    }
