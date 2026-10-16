"""Unit tests for cover URL resolution (no database required)."""

from unittest.mock import patch
from types import SimpleNamespace

from oneirodex.utils.cover_url import resolve_cover_url, resolve_game_cover_url


class _FakeImage:
    def __init__(self, url, download_url=None, is_downloaded=False):
        self.url = url
        self.download_url = download_url
        self.is_downloaded = is_downloaded


def _static_url(filename):
    return f'/static/{filename}'


@patch('oneirodex.utils.cover_url.static_asset_url', side_effect=_static_url)
def test_resolve_cover_url_default_when_missing(mock_url_for):
    assert resolve_cover_url(None) == '/static/newstyle/default_cover.jpg'
    assert resolve_cover_url(_FakeImage(url='')) == '/static/newstyle/default_cover.jpg'


@patch('oneirodex.utils.cover_url.static_asset_url', side_effect=_static_url)
def test_resolve_cover_url_empty_url_uses_download_url(mock_url_for):
    image = _FakeImage(url='', download_url='https://images.igdb.com/cover.jpg')
    assert resolve_cover_url(image) == 'https://images.igdb.com/cover.jpg'


@patch('oneirodex.utils.cover_url.static_asset_url', side_effect=_static_url)
def test_resolve_cover_url_accepts_string_path(mock_url_for):
    assert resolve_cover_url('https://cdn.example/a.jpg') == 'https://cdn.example/a.jpg'
    assert resolve_cover_url('//images.igdb.com/co.jpg') == 'https://images.igdb.com/co.jpg'


@patch('oneirodex.utils.cover_url._local_cover_exists', return_value=False)
@patch('oneirodex.utils.cover_url.static_asset_url', side_effect=_static_url)
def test_resolve_cover_url_uses_download_url_when_not_downloaded(mock_url_for, mock_exists):
    image = _FakeImage(
        url='cover_local.jpg',
        download_url='https://images.igdb.com/cover.jpg',
        is_downloaded=False,
    )
    assert resolve_cover_url(image) == 'https://images.igdb.com/cover.jpg'


@patch('oneirodex.utils.cover_url._local_cover_exists', return_value=True)
@patch('oneirodex.utils.cover_url.static_asset_url', side_effect=_static_url)
def test_resolve_cover_url_local_static_when_downloaded(mock_url_for, mock_exists):
    image = _FakeImage(url='abc.jpg', is_downloaded=True)
    assert resolve_cover_url(image) == '/static/library/images/abc.jpg'


@patch('oneirodex.utils.cover_url._local_cover_exists', return_value=False)
@patch('oneirodex.utils.cover_url.static_asset_url', side_effect=_static_url)
def test_resolve_cover_url_default_for_undownloaded_local_path(mock_url_for, mock_exists):
    image = _FakeImage(url='missing_local.jpg', is_downloaded=False)
    assert resolve_cover_url(image) == '/static/newstyle/default_cover.jpg'


@patch('oneirodex.utils.cover_url.static_asset_url', side_effect=_static_url)
def test_resolve_cover_url_passes_through_http_url(mock_url_for):
    image = _FakeImage(url='https://cdn.example/a.jpg', is_downloaded=False)
    assert resolve_cover_url(image) == 'https://cdn.example/a.jpg'


@patch('oneirodex.utils.cover_url._local_cover_exists', return_value=False)
@patch('oneirodex.utils.cover_url.static_asset_url', side_effect=_static_url)
def test_resolve_cover_url_falls_back_when_downloaded_file_missing(mock_url_for, mock_exists):
    image = _FakeImage(
        url='gone.jpg',
        download_url='//images.igdb.com/igdb/image/upload/t_original/co.jpg',
        is_downloaded=True,
    )
    assert resolve_cover_url(image) == 'https://images.igdb.com/igdb/image/upload/t_original/co.jpg'


@patch('oneirodex.utils.cover_url.static_asset_url', side_effect=_static_url)
def test_resolve_cover_url_normalizes_protocol_relative_primary_url(mock_url_for):
    image = _FakeImage(url='//images.igdb.com/co.jpg', is_downloaded=False)
    assert resolve_cover_url(image) == 'https://images.igdb.com/co.jpg'


class _FakeGame:
    def __init__(self, name, cover=None):
        self.name = name
        self.cover = cover


@patch('oneirodex.utils.cover_url.static_asset_url', side_effect=_static_url)
def test_missing_cover_generates_titled_placeholder_file(mock_url_for, tmp_path):
    """No cover + a title should render a branded per-title JPEG, not the boring default."""
    with patch('oneirodex.utils.cover_url.generated_root', return_value=tmp_path):
        url = resolve_cover_url(None, title='Chrono Trigger')

    assert url.startswith('/static/library/generated/covers/')
    assert url.endswith('_default.jpg')
    generated = list((tmp_path / 'covers').glob('*.jpg'))
    assert len(generated) == 1
    assert generated[0].stat().st_size > 0


@patch('oneirodex.utils.cover_url.static_asset_url', side_effect=_static_url)
def test_missing_cover_placeholder_is_cached_per_title(mock_url_for, tmp_path):
    """A second lookup for the same title reuses the cached file (no re-render)."""
    with patch('oneirodex.utils.cover_url.generated_root', return_value=tmp_path):
        first = resolve_cover_url(None, title='Chrono Trigger')
        second = resolve_cover_url(None, title='Chrono Trigger')

    assert first == second
    assert len(list((tmp_path / 'covers').glob('*.jpg'))) == 1


@patch('oneirodex.utils.cover_url.static_asset_url', side_effect=_static_url)
def test_missing_cover_without_title_still_uses_static_default(mock_url_for, tmp_path):
    with patch('oneirodex.utils.cover_url.generated_root', return_value=tmp_path):
        url = resolve_cover_url(None)

    assert url == '/static/newstyle/default_cover.jpg'
    assert not (tmp_path / 'covers').exists()


def test_cover_urls_use_explicit_app_config_without_flask_context():
    app = SimpleNamespace(
        config={'APPLICATION_ROOT': '/prefix'},
        static_url_path='/assets',
        root_path='C:/oneirodex',
    )

    assert resolve_cover_url(None, app=app) == '/prefix/assets/newstyle/default_cover.jpg'


@patch('oneirodex.utils.cover_url.static_asset_url', side_effect=_static_url)
def test_resolve_game_cover_url_uses_game_name_for_placeholder(mock_url_for, tmp_path):
    game = _FakeGame(name='Secret of Mana')
    with patch('oneirodex.utils.cover_url.generated_root', return_value=tmp_path):
        url = resolve_game_cover_url(game, cover_image=None)

    assert '/static/library/generated/covers/' in url


@patch('oneirodex.utils.cover_url.generated_root', side_effect=RuntimeError('no app context'))
@patch('oneirodex.utils.cover_url.static_asset_url', side_effect=_static_url)
def test_missing_cover_falls_back_to_static_default_on_render_failure(mock_url_for, mock_root):
    """Rendering failures (missing app context, disk errors, ...) must not break cover resolution."""
    assert resolve_cover_url(None, title='Chrono Trigger') == '/static/newstyle/default_cover.jpg'
