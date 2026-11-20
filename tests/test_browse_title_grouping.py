"""Copies of one title across systems collapse to a single browse row.

The grid shows one tile per row in one library, so a household holding a game on
three systems saw three unrelated tiles. Grouping happens inside the query —
Postgres computes the pairing key and `DISTINCT ON` picks the representative —
so the things most worth pinning are the ones a post-query dedupe would get
wrong: that the *count* still counts titles, and that a page stays full.
"""

from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from oneirodex.models import Game, GlobalSettings, Library, User
from oneirodex.platform import LibraryPlatform


@pytest.fixture
def group_user(db_session):
    tag = uuid4().hex[:8]
    user = User(
        name=f'group-{tag}',
        email=f'group-{tag}@example.com',
        password_hash='unused',
        role='user',
        user_id=str(uuid4()),
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def single_settings_row(db_session):
    """browse_games reads one GlobalSettings; dirty test DBs may hold several."""
    rows = db_session.execute(
        select(GlobalSettings).order_by(GlobalSettings.id)
    ).scalars().all()
    if len(rows) > 1:
        db_session.execute(delete(GlobalSettings).where(GlobalSettings.id != rows[0].id))
        db_session.commit()
    elif not rows:
        db_session.add(GlobalSettings())
        db_session.commit()


def _library(db_session, platform):
    library = Library(
        name=f'{platform.name} {uuid4().hex[:8]}',
        platform=platform,
        display_order=1,
    )
    db_session.add(library)
    db_session.commit()
    return library


def _game(db_session, library, name):
    game = Game(
        uuid=str(uuid4()),
        name=name,
        library_uuid=library.uuid,
        full_disk_path=f'/test/group/{uuid4().hex}',
    )
    db_session.add(game)
    db_session.commit()
    return game


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def _rows(response, name):
    return [g for g in response.get_json()['games'] if g['name'] == name]


@pytest.fixture
def three_systems(db_session, single_settings_row):
    """One title on NES, SNES and GBA — the example this was built against."""
    title = f'Grouped Quest {uuid4().hex[:8]}'
    libraries = {}
    for platform in (LibraryPlatform.NES, LibraryPlatform.SNES, LibraryPlatform.GBA):
        library = _library(db_session, platform)
        libraries[platform.name] = library
        _game(db_session, library, title)
    return title, libraries


def test_one_tile_per_title_not_per_copy(client, group_user, three_systems):
    title, _ = three_systems
    _login(client, group_user)

    response = client.get('/browse_games?per_page=1000')
    assert response.status_code == 200
    assert len(_rows(response, title)) == 1


def test_the_representative_is_the_newest_hardware(client, group_user, three_systems):
    """GBA (2001) beats SNES (1990) and NES (1983) — not scan order, not id."""
    title, _ = three_systems
    _login(client, group_user)

    row = _rows(client.get('/browse_games?per_page=1000'), title)[0]
    assert row['library_platform'] == 'GBA'
    assert row['edition_platforms'] == ['GBA', 'SNES', 'NES']
    assert row['edition_count'] == 3


def test_a_system_filter_keeps_that_system_copy(client, group_user, three_systems):
    """Filtered to NES you are looking at the NES copy, so the row must be it."""
    title, _ = three_systems
    _login(client, group_user)

    response = client.get('/browse_games?library_platform=NES&per_page=1000')
    rows = _rows(response, title)
    assert len(rows) == 1
    assert rows[0]['library_platform'] == 'NES'


def test_a_filtered_row_still_knows_the_systems_the_filter_excluded(
    client, group_user, three_systems,
):
    """The badge reads "NES +2", which needs the rows the NES filter removed.

    This is the assertion that fails if the edition lookup is ever folded into
    the main query instead of being its own ACL-scoped pass.
    """
    title, _ = three_systems
    _login(client, group_user)

    response = client.get('/browse_games?library_platform=NES&per_page=1000')
    row = _rows(response, title)[0]
    assert row['edition_count'] == 3
    assert set(row['edition_platforms']) == {'NES', 'SNES', 'GBA'}


def test_the_total_counts_titles_so_pages_stay_full(
    client, db_session, group_user, single_settings_row,
):
    """A post-query dedupe would return short pages and an inflated total.

    Fifty copies of twenty-five titles, two per title. The smallest page size
    the API accepts is 20 (`normalize_page_size` allow-lists 20…1000), so
    twenty-five titles is what it takes to see a second page at all: the total
    must be titles rather than copies, page one must be *full* with twenty
    distinct titles, and page two must hold the remaining five.
    """
    tag = uuid4().hex[:8]
    nes = _library(db_session, LibraryPlatform.NES)
    snes = _library(db_session, LibraryPlatform.SNES)
    for index in range(25):
        title = f'Paged {tag} {index:02d}'
        _game(db_session, nes, title)
        _game(db_session, snes, title)
    _login(client, group_user)

    first = client.get(
        f'/browse_games?per_page=20&page=1&name=Paged {tag}'
    ).get_json()
    assert first['total'] == 25, 'total counted copies, not titles'
    assert first['pages'] == 2
    assert len(first['games']) == 20, 'a short page means dedupe ran after paging'
    assert len({row['name'] for row in first['games']}) == 20

    second = client.get(
        f'/browse_games?per_page=20&page=2&name=Paged {tag}'
    ).get_json()
    assert len(second['games']) == 5
    # No title may appear on both pages.
    assert not (
        {row['name'] for row in first['games']} & {row['name'] for row in second['games']}
    )


def test_titles_pair_on_punctuation_and_case(
    client, db_session, group_user, single_settings_row,
):
    """The same normalisation the preview uses, computed in SQL."""
    tag = uuid4().hex[:8]
    nes = _library(db_session, LibraryPlatform.NES)
    snes = _library(db_session, LibraryPlatform.SNES)
    _game(db_session, nes, f'Final Fantasy: VII {tag}')
    _game(db_session, snes, f'final   fantasy vii {tag}')
    _login(client, group_user)

    rows = [
        row
        for row in client.get(f'/browse_games?per_page=1000&name={tag}').get_json()['games']
        if tag in row['name']
    ]
    assert len(rows) == 1, 'punctuation and case should not split a title'
    assert rows[0]['edition_count'] == 2


def test_different_titles_are_not_collapsed(
    client, db_session, group_user, single_settings_row,
):
    """The guard against over-eager pairing: two games, two tiles."""
    tag = uuid4().hex[:8]
    nes = _library(db_session, LibraryPlatform.NES)
    _game(db_session, nes, f'Zelda One {tag}')
    _game(db_session, nes, f'Zelda Two {tag}')
    _login(client, group_user)

    rows = [
        row
        for row in client.get(f'/browse_games?per_page=1000&name={tag}').get_json()['games']
        if tag in row['name']
    ]
    assert len(rows) == 2


def test_a_lone_copy_reports_its_own_system(
    client, db_session, group_user, single_settings_row,
):
    """No grouping information must not mean an empty chip."""
    tag = uuid4().hex[:8]
    nes = _library(db_session, LibraryPlatform.NES)
    _game(db_session, nes, f'Only Here {tag}')
    _login(client, group_user)

    row = [
        row
        for row in client.get(f'/browse_games?per_page=1000&name={tag}').get_json()['games']
        if tag in row['name']
    ][0]
    assert row['edition_platforms'] == ['NES']
    assert row['edition_count'] == 1


def test_script_titles_and_edition_picker_follow_same_identity(db_session, group_user, single_settings_row):
    from werkzeug.datastructures import MultiDict
    from oneirodex.utils.browse_query import run_browse_query
    from oneirodex.utils.game_editions import _edition_games

    nes = _library(db_session, LibraryPlatform.NES)
    pc = _library(db_session, LibraryPlatform.PCWIN)
    nested = _game(db_session, nes, 'First: Flight')
    alternate = _game(db_session, pc, 'First Flight')
    titles = ['星の旅', '海の夢', '!!!', '???', 'نور', 'پرتو']
    for name in titles:
        _game(db_session, nes, name)
    matches = run_browse_query(MultiDict(), group_user)
    assert matches.total == len(titles) + 1
    assert set(titles) <= {game.name for game in matches.games}
    assert {g.uuid for g in _edition_games(nested, group_user)} == {nested.uuid, alternate.uuid}
    alternate.name = 'Different Flight'
    db_session.commit()
    assert [g.uuid for g in _edition_games(nested, group_user)] == [nested.uuid]


def test_category_accepts_label_and_enum_and_bounds_page(db_session, group_user, single_settings_row):
    from werkzeug.datastructures import MultiDict
    from oneirodex.models import Category
    from oneirodex.utils.browse_query import run_browse_query

    game = _game(db_session, _library(db_session, LibraryPlatform.NES), 'A game')
    game.category = Category.MAIN_GAME
    db_session.commit()
    for value in (Category.MAIN_GAME.name, Category.MAIN_GAME.value):
        result = run_browse_query(MultiDict({'category': value, 'page': '0'}), group_user)
        assert result.page == 1
        assert [g.uuid for g in result.games] == [game.uuid]
    assert run_browse_query(MultiDict({'category': 'no such category'}), group_user).total == 0
