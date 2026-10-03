# forms.py
import re
from flask_wtf import FlaskForm
from wtforms import StringField, IntegerField, SelectField, BooleanField, SubmitField, PasswordField, TextAreaField, RadioField, FloatField, ValidationError, HiddenField
from flask_wtf.file import FileField, FileAllowed, FileRequired
from wtforms.validators import DataRequired, Length, Optional, NumberRange, Regexp, URL, Email, EqualTo
from wtforms.widgets import TextInput
from wtforms_sqlalchemy.fields import QuerySelectMultipleField
from wtforms.widgets import ListWidget, CheckboxInput
from wtforms.fields import DateField
from oneirodex.models import Status, Category, genre_choices, game_mode_choices, theme_choices, platform_choices, player_perspective_choices, LibraryPlatform
from urllib.parse import urlparse
from oneirodex.utils.functions import comma_separated_urls
from oneirodex.utils.themes import ThemeManager
from oneirodex.utils.icon_themes import list_icon_packs
from flask import current_app


def safe_url_validator(form, field):
    """Validate URL scheme is http or https only."""
    if field.data and field.data.strip():
        try:
            parsed = urlparse(field.data.strip())
            if parsed.scheme and parsed.scheme.lower() not in ['http', 'https']:
                raise ValidationError('Only HTTP and HTTPS URLs are allowed.')
            elif parsed.scheme and parsed.scheme.lower() in ['javascript', 'file', 'ftp', 'data']:
                raise ValidationError('Only HTTP and HTTPS URLs are allowed.')
        except Exception:
            raise ValidationError('Invalid URL format.')

class UpdateUnmatchedFolderForm(FlaskForm):
    folder_id = HiddenField('Folder ID', validators=[DataRequired()])
    new_status = HiddenField('New Status', default='Ignore')
    submit = SubmitField('Ignore')

class SetupForm(FlaskForm):
    username = StringField('Admin Username', validators=[
        DataRequired(),
        Length(min=3, max=64),
        Regexp(r'^[\w.]+$', message="Username can only contain letters, numbers, dots and underscores")
    ])
    email = StringField('Admin Email', validators=[
        DataRequired(),
        Email(),
        Length(max=120)
    ])
    password = PasswordField('Password', validators=[
        DataRequired(),
        Length(min=8, message='Password must be at least 8 characters long')
    ])
    confirm_password = PasswordField('Confirm Password', validators=[
        DataRequired(),
        EqualTo('password', message='Passwords must match')
    ])
    submit = SubmitField('Next Step')

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')
    
class ResetPasswordRequestForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    submit = SubmitField('Request Password Reset')

class AutoScanForm(FlaskForm):
    # Empty path is allowed and means "scan the configured base directory"
    folder_path = StringField('Browse Folder Path', validators=[Optional()])
    # Which declared scan location folder_path is relative to. Empty keeps the
    # historical behaviour of resolving against the OS base folder.
    library_root = StringField('Scan location', validators=[Optional()])
    library_uuid = SelectField('Select Library', coerce=str, validators=[DataRequired()])
    scan_mode = RadioField(
        'My Games are:',
        choices=[
            ('auto', 'Auto (detect)'),
            ('folders', 'Folders'),
            ('files', 'Files'),
        ],
        default='auto',
    )
    remove_missing = BooleanField('Remove missing games')
    download_missing_images = BooleanField('Download missing images')
    force_updates_extras_scan = BooleanField('Force scan for new updates and extras on existing games')
    fetch_hltb = BooleanField('Fetch HowLongToBeat data', default=True)
    force_hltb_refetch = BooleanField('Force refetch HLTB for existing games')
    schedule = SelectField(
        'Repeat schedule',
        choices=[
            ('', 'Once (no repeat)'),
            ('8_hours', 'Every 8 hours'),
            ('24_hours', 'Every 24 hours'),
            ('48_hours', 'Every 48 hours'),
            ('interval', 'Every N minutes / hours'),
            ('cron', 'Cron expression'),
        ],
        default='',
        validators=[Optional()],
    )
    schedule_interval_value = IntegerField(
        'Interval',
        validators=[Optional(), NumberRange(min=1, max=10080)],
        default=6,
    )
    schedule_interval_unit = SelectField(
        'Unit',
        choices=[('hours', 'Hours'), ('minutes', 'Minutes')],
        default='hours',
        validators=[Optional()],
    )
    schedule_cron = StringField(
        # Next-fire is computed in UTC (oneirodex/utils/cron_schedule.py), so the
        # label has to say so: "0 3 * * *" from a household in America/Chicago is
        # a 9pm or 10pm local scan, not the overnight one the operator intended.
        'Cron expression (UTC)',
        description='Five fields, evaluated in UTC. Day-of-month and day-of-week '
                    'follow crontab: when both are set, either one fires.',
        validators=[Optional(), Length(max=64)],
        render_kw={
            'placeholder': '0 */6 * * *',
            'title': 'Minute hour day-of-month month day-of-week, in UTC',
        },
    )
    submit = SubmitField('AutoScan')


class WhitelistForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    submit = SubmitField('Add to Whitelist')

class EditProfileForm(FlaskForm):
    avatar = FileField('Profile Avatar', validators=[
        FileAllowed(['jpg', 'jpeg', 'png', 'gif'], 'Images only!')
    ])
    
class ScanFolderForm(FlaskForm):
    # Empty path is allowed and means "scan the configured base directory"
    folder_path = StringField('Folder Path', validators=[Optional()])
    library_root = StringField('Scan location', validators=[Optional()])
    scan_mode = RadioField(
        'My Games are:',
        choices=[
            ('auto', 'Auto (detect)'),
            ('folders', 'Folders'),
            ('files', 'Files'),
        ],
        default='auto',
    )
    library_uuid = SelectField('Select Library', coerce=str, validators=[DataRequired()])
    force_updates_extras_scan = BooleanField('Force scan for new updates and extras on existing games')
    fetch_hltb = BooleanField('Fetch HowLongToBeat data', default=True)
    force_hltb_refetch = BooleanField('Force refetch HLTB for existing games')
    scan = SubmitField('List Games')
    cancel = SubmitField('Cancel')


class InviteForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email(message='Invalid email.')], render_kw={"placeholder": "Enter email to invite"})
    submit = SubmitField('Send Invite')

class UserDetailForm(FlaskForm):
    submit = SubmitField('Save')
    cancel = SubmitField('Cancel')
    about = TextAreaField('About')


class UserPasswordForm(FlaskForm):
    password = PasswordField('New Password', validators=[DataRequired(), Length(min=8)])
    confirm_password = PasswordField('Confirm Password', validators=[
        DataRequired(), EqualTo('password', message='Passwords must match')])
    submit = SubmitField('Save')
    cancel = SubmitField('Cancel')


class ChangePasswordForm(UserPasswordForm):
    current_password = PasswordField('Current Password', validators=[DataRequired()])


class NewsletterForm(FlaskForm):
    subject = StringField('Subject', validators=[DataRequired()])
    content = TextAreaField('Content', validators=[DataRequired()])
    recipients = StringField('Recipients')
    send = SubmitField('Send')

class EditUserForm(FlaskForm):

    name = SelectField('Name', validators=[DataRequired()])
    email = StringField('Email', validators=[DataRequired(), Email()])
    role = StringField('Role', validators=[DataRequired()])
    state = RadioField('State', choices=[('1', 'Active'), ('0', 'Inactive')])
    avatarpath = StringField('Avatar Path', validators=[DataRequired()])
    submit = SubmitField('Save')
    
    
class UserManagementForm(FlaskForm):
    user_id = SelectField('Choose handle', coerce=int)
    name = StringField('User Name', validators=[Length(max=64)])
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=120)])
    role = StringField('Role', validators=[Length(max=64)])
    state = BooleanField('Account Enabled')
    search = StringField('Search Users')
    is_email_verified = BooleanField('Email Verified', validators=[Optional()])
    about = TextAreaField('Admin Notes', validators=[Optional()])
    submit = SubmitField('Save Changes')
    delete = SubmitField('Walk the plank!')


class CreateUserForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    
    def validate_username(self, field):
        if field.data.lower() == 'system':
            raise ValidationError("'system' is a reserved username and cannot be used.")
        # Check for valid characters
        if not re.match(r'^[\w.]+$', field.data):
            raise ValidationError("Username can only contain letters, numbers, dots and underscores")
        if len(field.data) < 3 or len(field.data) > 64:
            raise ValidationError("Username must be between 3 and 64 characters long")
    
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Create User')

    
class IGDBApiForm(FlaskForm):
    endpoint = SelectField('Select API Endpoint', choices=[

        ('https://api.igdb.com/v4/games', 'Games'),
        ('https://api.igdb.com/v4/search', 'Search'),
        ('https://api.igdb.com/v4/screenshots', 'Screenshots'),
        ('https://api.igdb.com/v4/covers', 'Covers'),
        ('https://api.igdb.com/v4/game_videos', 'Game Videos'),
        ('https://api.igdb.com/v4/keywords', 'Keywords'),
        ('https://api.igdb.com/v4/involved_companies', 'InvolvedCompanies'),
        ('https://api.igdb.com/v4/platforms', 'Platforms'),

    ], validators=[DataRequired()])
    query = TextAreaField('Query', validators=[DataRequired()])
    submit = SubmitField('Submit')


class AddGameForm(FlaskForm):
    # Existing fields
    igdb_id = IntegerField('IGDB ID', validators=[DataRequired(), NumberRange(min=1, max=9999999999)], widget=TextInput())
    name = StringField('Name', validators=[DataRequired()])
    summary = TextAreaField('Summary', validators=[Optional()])
    storyline = TextAreaField('Storyline', validators=[Optional()])
    url = StringField('URL', validators=[Optional(), URL(), safe_url_validator])
    full_disk_path = StringField('Full Disk Path', validators=[DataRequired()], widget=TextInput())
    video_urls = StringField('Video URLs', validators=[Optional(), comma_separated_urls])
    aggregated_rating = FloatField('Aggregated Rating', validators=[Optional()])
    first_release_date = DateField('First Release Date', format='%Y-%m-%d', validators=[Optional()])
    status = SelectField('Status', choices=[(choice.name, choice.value) for choice in Status], coerce=str, validators=[Optional()])
    category = SelectField('Category', choices=[(choice.name, choice.value) for choice in Category], coerce=str, validators=[Optional()])
    genres = QuerySelectMultipleField('Genres', query_factory=genre_choices, get_label='name', widget=ListWidget(prefix_label=False), option_widget=CheckboxInput())
    game_modes = QuerySelectMultipleField('Game Modes', query_factory=game_mode_choices, get_label='name', widget=ListWidget(prefix_label=False), option_widget=CheckboxInput())
    themes = QuerySelectMultipleField('Themes', query_factory=theme_choices, get_label='name', widget=ListWidget(prefix_label=False), option_widget=CheckboxInput())
    platforms = QuerySelectMultipleField('Platforms', query_factory=platform_choices, get_label='name', widget=ListWidget(prefix_label=False), option_widget=CheckboxInput())
    player_perspectives = QuerySelectMultipleField('Player Perspectives', query_factory=player_perspective_choices, get_label='name', widget=ListWidget(prefix_label=False), option_widget=CheckboxInput())
    developer = StringField('Developer', validators=[Optional()])
    publisher = StringField('Publisher', validators=[Optional()])
    library_uuid = SelectField('Library', coerce=str, validators=[DataRequired()])
    submit = SubmitField('Save')    
    
class CsrfProtectForm(FlaskForm):
    pass

class CsrfForm(FlaskForm):
    pass 

class ReleaseGroupForm(FlaskForm):
    filter_pattern = StringField('Scanning Filter', validators=[DataRequired()])
    case_sensitive = SelectField('Case-Sensitive Filter', choices=[('no', 'No'), ('yes', 'Yes')], default='no')
    submit = SubmitField('Add')
    
class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=8)])
    
    def validate_username(self, field):
        if field.data.lower() == 'system':
            raise ValidationError("'system' is a reserved username and cannot be used.")
        # Check for valid characters
        if not re.match(r'^[\w.]+$', field.data):
            raise ValidationError("Username can only contain letters, numbers, dots and underscores")
        if len(field.data) < 3 or len(field.data) > 64:
            raise ValidationError("Username must be between 3 and 64 characters long")
    
    submit = SubmitField('Register')

class UserPreferencesForm(FlaskForm):
    items_per_page_choices = [
        ('20', '20'),
        ('50', '50'),
        ('100', '100'),
        ('200', '200'),
        ('300', '300'),
        ('400', '400'),
        ('500', '500'),
        ('1000', '1000'),
    ]
    default_sort_choices = [
        ('name', 'Name'),
        ('rating', 'Rating'),
        ('first_release_date', 'Date Released'),
        ('date_identified', 'Date Added'),
        ('size', 'Filesize')
    ]
    default_sort_order_choices = [
        ('asc', 'Ascending'),
        ('desc', 'Descending')
    ]

    items_per_page = SelectField('Max items per Page', choices=items_per_page_choices, coerce=int)
    default_sort = SelectField('Default Sort', choices=default_sort_choices)
    default_sort_order = SelectField('Default Sort Order', choices=default_sort_order_choices)
    theme = SelectField('Theme', choices=[('default', 'Default (system)')])  # folder slug `default`
    icon_pack = SelectField('Icon pack', choices=[('outline', 'Outline')])
    font = SelectField('Font', choices=[('system-ui', 'System UI (default)')])
    tile_size = StringField('Tile size %', default='50')
    show_tile_titles = BooleanField('Show titles under tiles', default=True)
    # Browser play engine. '' = the admin default. Choices are filled in
    # __init__ from what is installed on this box; the field is only rendered
    # when the admin allows member choice (see settings_panel).
    browser_player_engine = SelectField(
        'Play in browser with',
        choices=[('', 'Server default')],
        default='',
    )
    preferred_game_locale = SelectField(
        'Preferred game language',
        choices=[
            ('en-US', 'English (US)'),
            ('en-GB', 'English (UK)'),
            ('ja-JP', 'Japanese'),
            ('es', 'Spanish'),
            ('fr', 'French'),
            ('de', 'German'),
        ],
        default='en-US',
    )
    submit = SubmitField('Save Preferences')

    def __init__(self, *args, **kwargs):
        super(UserPreferencesForm, self).__init__(*args, **kwargs)
        theme_manager = ThemeManager(current_app)
        installed_themes = theme_manager.get_installed_themes()
        # Value must be the theme folder slug (theme_asset path), not display name
        self.theme.choices = [('default', 'Default (system)')] + [
            (theme.get('folder') or theme['name'], theme['name'])
            for theme in installed_themes
            if (theme.get('folder') or theme['name']) != 'default'
        ]
        try:
            packs = list_icon_packs()
            self.icon_pack.choices = [
                (p['id'], p.get('name') or p['id']) for p in packs
            ] or [('outline', 'Outline')]
        except Exception:
            self.icon_pack.choices = [('outline', 'Outline')]
        try:
            from oneirodex.utils.theme_fonts import available_fonts

            # A face whose file is missing still appears (the picker stays
            # stable) but says so, rather than silently falling back.
            self.font.choices = [
                (key, entry['label'] if entry.get('installed')
                 else f"{entry['label']} — not installed")
                for key, entry in available_fonts().items()
            ] or [('system-ui', 'System UI (default)')]
        except Exception:
            self.font.choices = [('system-ui', 'System UI (default)')]
        try:
            from oneirodex.utils.browser_player import (
                KNOWN_ENGINES,
                engine_label,
                get_browser_player_settings,
            )

            # Every known engine, not just the installed ones: the picker is
            # only *shown* when both are installed, but a stored choice for an
            # engine that has since been removed must still round-trip through
            # a whole-form save. The resolver ignores it until it is back.
            default_engine = get_browser_player_settings()['browser_player_default']
            self.browser_player_engine.choices = [
                ('', f'Server default ({engine_label(default_engine)})'),
            ] + [(engine, engine_label(engine)) for engine in KNOWN_ENGINES]
        except Exception:
            self.browser_player_engine.choices = [('', 'Server default')]


class LibraryForm(FlaskForm):
    name = StringField('Library Name', validators=[DataRequired()])
    platform = SelectField('Platform', choices=[(choice.value, choice.name) for choice in LibraryPlatform], validators=[DataRequired()])
    scan_depth = SelectField(
        'Scan depth',
        choices=[
            ('1', '1 — game folders directly in the scan root'),
            ('2', '2 — unwrap letter buckets (_a … _z, _#) then games'),
        ],
        default='1',
        coerce=int,
        validators=[DataRequired()],
    )
    watch_enabled = SelectField(
        'Incremental watch',
        choices=[
            ('default', 'Follow global (ONEIRODEX_LIBRARY_WATCH)'),
            ('on', 'Prefer watch when global is on'),
            ('off', 'Opt out (never watch this library)'),
        ],
        default='default',
        validators=[DataRequired()],
    )
    image = FileField('Library Image', validators=[FileAllowed(['jpg', 'jpeg', 'png', 'gif', 'webp'], 'Images only!')])


def coerce_library_watch_enabled(raw):
    """Map LibraryForm watch_enabled → DB null/True/False."""
    text = (str(raw) if raw is not None else 'default').strip().lower()
    if text in ('off', '0', 'false', 'no', 'disabled'):
        return False
    if text in ('on', '1', 'true', 'yes', 'enabled'):
        return True
    return None


def library_watch_form_value(flag):
    """Map DB watch_enabled → LibraryForm choice value."""
    if flag is False:
        return 'off'
    if flag is True:
        return 'on'
    return 'default'

class ThemeUploadForm(FlaskForm):
    theme_zip = FileField('Theme ZIP File', validators=[
        FileRequired(),
        FileAllowed(['zip'], 'ZIP files only!')
    ])
    submit = SubmitField('Upload Theme')

class IGDBSetupForm(FlaskForm):
    igdb_client_id = StringField('Client ID', validators=[
        DataRequired(),
        Length(min=20, max=50, message='Client ID must be between 20 and 50 characters')
    ])
    igdb_client_secret = StringField('Client Secret', validators=[
        DataRequired(),
        Length(min=20, max=50, message='Client Secret must be between 20 and 50 characters')
    ])
    submit = SubmitField('Complete Setup')
