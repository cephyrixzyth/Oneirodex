"""Implemented store capabilities, separate from account readiness and future plans.

This registry never reads credentials or calls a provider. Capabilities describe
existing adapters, not proof that a particular member can use them successfully.
"""
from copy import deepcopy

# Existing route IDs stay stable; aliases are display/search metadata only.
_DEFINITIONS = (
    ('steam', 'Steam', 'official', 'account_id', 'live', True, []),
    ('gog', 'GOG', 'unofficial', 'token', 'live', True, []),
    ('epic', 'Epic Games', 'unofficial', 'token', 'live', True, []),
    ('amazon', 'Amazon Games', 'unofficial', 'token', 'live', True, []),
    ('xbox', 'Microsoft / Xbox', 'unofficial_opt_in', 'token', 'snapshot', True, ['microsoft']),
    ('psn', 'PlayStation', 'unofficial_opt_in', 'token', 'snapshot', True, ['sony']),
    ('meta_quest', 'Meta Quest', 'import', 'none', 'snapshot', True, []),
    ('playnite', 'Playnite', 'import', 'none', 'snapshot', False, []),
    ('humble', 'Humble Bundle', 'unavailable', 'none', 'unavailable', False, []),
    ('ea', 'EA app', 'unavailable', 'none', 'unavailable', False, ['origin']),
    ('battlenet', 'Battle.net', 'unavailable', 'none', 'unavailable', False, []),
    ('ubisoft', 'Ubisoft Connect', 'unavailable', 'none', 'unavailable', False, ['uplay']),
    ('itch', 'itch.io', 'unavailable', 'none', 'unavailable', False, []),
    ('nintendo', 'Nintendo', 'unavailable', 'none', 'unavailable', False, []),
)

REGISTER_ACCOUNT_STORES = frozenset({'steam', 'gog', 'epic', 'amazon', 'xbox', 'psn', 'meta_quest'})


def provider_capabilities(*, enabled=True, unofficial_stores=frozenset()):
    """Return fresh JSON-safe records; caller supplies operator policy, never keys."""
    providers = []
    for key, name, authority, auth, listing, csv, aliases in _DEFINITIONS:
        opted_in = key in unofficial_stores
        if authority == 'unofficial_opt_in' and opted_in:
            listing = 'live'
        supported = listing != 'unavailable'
        providers.append({
            'id': key,
            'name': name,
            'aliases': deepcopy(aliases),
            'authority': authority,
            'capabilities': {
                'connect': auth if key in REGISTER_ACCOUNT_STORES and auth != 'none' else 'unavailable',
                'library_listing': listing,
                'csv_import': 'snapshot' if csv else 'unavailable',
                'file_import': 'playnite_export' if key == 'playnite' else 'unavailable',
                'identity_matching': 'existing_register' if supported else 'unavailable',
                'store_filter': 'recorded_ownership' if supported else 'unavailable',
                'install': 'unavailable',
                'update': 'unavailable',
                'launch': 'unavailable',
                'cloud_save': 'unavailable',
            },
            'policy_enabled': bool(enabled and supported),
            'requires_unofficial_opt_in': authority == 'unofficial_opt_in',
            'unofficial_opted_in': bool(opted_in) if authority == 'unofficial_opt_in' else False,
            'account_readiness': 'not_checked',
            'ownership_caveat': (
                'Imported or returned titles are source records, not a verified exhaustive entitlement list.'
                if supported else 'No ownership adapter is implemented for this service.'
            ),
        })
    return providers
