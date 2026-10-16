"""WTForms contracts used by FastAPI without Flask-WTF or Flask contexts."""
from __future__ import annotations

from wtforms import BooleanField, Form, SelectField, StringField, SubmitField

from oneirodex.utils.icon_themes import list_icon_packs
from oneirodex.utils.preset_themes import theme_picker_groups
from oneirodex.utils.themes import ThemeManager


_TILE_LEGACY = {'S': '25', 'M': '50', 'L': '75', 'XL': '100'}


def normalize_tile_percent(raw) -> str:
    text = str(raw or '').strip().upper()
    if text in _TILE_LEGACY:
        return _TILE_LEGACY[text]
    try:
        value = int(text)
    except (TypeError, ValueError):
        return '50'
    return str(max(0, min(100, value)))


def stored_preference_formdata(prefs) -> dict:
    return {
        'items_per_page': str(getattr(prefs, 'items_per_page', None) or 50),
        'default_sort': getattr(prefs, 'default_sort', None) or 'name',
        'default_sort_order': getattr(prefs, 'default_sort_order', None) or 'asc',
        'theme': getattr(prefs, 'theme', None) or 'default',
        'icon_pack': getattr(prefs, 'icon_pack', None) or 'outline',
        'font': getattr(prefs, 'font', None) or 'system-ui',
        'tile_size': normalize_tile_percent(getattr(prefs, 'tile_size', None)),
        'show_tile_titles': 'true' if getattr(prefs, 'show_tile_titles', True) else 'false',
        'browser_player_engine': getattr(prefs, 'browser_player_engine', None) or '',
        'preferred_game_locale': getattr(prefs, 'preferred_game_locale', None) or 'en-US',
    }


class UserPreferencesForm(Form):
    items_per_page_choices = [
        ('20', '20'), ('50', '50'), ('100', '100'), ('200', '200'),
        ('300', '300'), ('400', '400'), ('500', '500'), ('1000', '1000'),
    ]
    default_sort_choices = [
        ('name', 'Name'), ('rating', 'Rating'),
        ('first_release_date', 'Date Released'),
        ('date_identified', 'Date Added'), ('size', 'Filesize'),
    ]
    default_sort_order_choices = [('asc', 'Ascending'), ('desc', 'Descending')]

    items_per_page = SelectField(
        'Max items per Page', choices=items_per_page_choices, coerce=int,
    )
    default_sort = SelectField('Default Sort', choices=default_sort_choices)
    default_sort_order = SelectField(
        'Default Sort Order', choices=default_sort_order_choices,
    )
    theme = SelectField('Theme', choices=[('default', 'Default (system)')])
    icon_pack = SelectField('Icon pack', choices=[('outline', 'Outline')])
    font = SelectField('Font', choices=[('system-ui', 'System UI (default)')])
    tile_size = StringField('Tile size %', default='50')
    show_tile_titles = BooleanField('Show titles under tiles', default=True)
    browser_player_engine = SelectField(
        'Play in browser with', choices=[('', 'Server default')], default='',
    )
    preferred_game_locale = SelectField(
        'Preferred game language',
        choices=[
            ('en-US', 'English (US)'), ('en-GB', 'English (UK)'),
            ('ja-JP', 'Japanese'), ('es', 'Spanish'), ('fr', 'French'),
            ('de', 'German'),
        ],
        default='en-US',
    )
    submit = SubmitField('Save Preferences')

    def __init__(self, *args, app=None, **kwargs):
        super().__init__(*args, **kwargs)
        if app is None:
            return
        installed_themes = ThemeManager(app).get_installed_themes()
        self.theme.choices = [('default', 'Default (system)')] + [
            (theme.get('folder') or theme['name'], theme['name'])
            for theme in installed_themes
            if (theme.get('folder') or theme['name']) != 'default'
        ]
        try:
            packs = list_icon_packs()
            self.icon_pack.choices = [
                (pack['id'], pack.get('name') or pack['id']) for pack in packs
            ] or [('outline', 'Outline')]
        except Exception:
            self.icon_pack.choices = [('outline', 'Outline')]
        try:
            from oneirodex.utils.theme_fonts import available_fonts

            self.font.choices = [
                (
                    key,
                    entry['label'] if entry.get('installed')
                    else f"{entry['label']} — not installed",
                )
                for key, entry in available_fonts().items()
            ] or [('system-ui', 'System UI (default)')]
        except Exception:
            self.font.choices = [('system-ui', 'System UI (default)')]
        try:
            from oneirodex.utils.browser_player import (
                KNOWN_ENGINES, engine_label, get_browser_player_settings,
            )

            default_engine = get_browser_player_settings()['browser_player_default']
            self.browser_player_engine.choices = [
                ('', f'Server default ({engine_label(default_engine)})'),
            ] + [(engine, engine_label(engine)) for engine in KNOWN_ENGINES]
        except Exception:
            self.browser_player_engine.choices = [('', 'Server default')]


__all__ = [
    'UserPreferencesForm', 'normalize_tile_percent', 'stored_preference_formdata',
]
