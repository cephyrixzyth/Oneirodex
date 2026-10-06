"""FEAT-D2 — PC cheat notes.

This reversed a locked stance, so the guardrails that survived the reversal are
the things worth pinning: `.cht` stays RetroArch-only, the PC surface is notes
rather than a trainer, and nothing here touches a game binary.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from flask import json
from sqlalchemy import text

from oneirodex import db
from oneirodex.models import Game, Library, LibraryPlatform, PcCheat, User
from oneirodex.utils.api_tokens import generate_api_token


@pytest.fixture(scope='function', autouse=True)
def clean(db_session):
    db_session.execute(text('TRUNCATE TABLE pc_cheats RESTART IDENTITY CASCADE'))
    db_session.execute(text('TRUNCATE TABLE games RESTART IDENTITY CASCADE'))
    db_session.execute(text('TRUNCATE TABLE libraries RESTART IDENTITY CASCADE'))
    db_session.commit()


def _user(db_session, role='admin'):
    uid = str(uuid4())
    user = User(
        name=f'{role}_{uid[:8]}',
        email=f'{role}_{uid[:8]}@example.com',
        password_hash='hashed_password',
        role=role,
        user_id=uid,
        avatarpath='newstyle/avatar_default.jpg',
        invite_quota=5,
        is_email_verified=True,
    )
    user.set_password('testpassword123')
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def admin_user(db_session):
    return _user(db_session, 'admin')


def _game_on(db_session, platform, name='A Game'):
    lib = Library(name=f'{platform.name} Lib', platform=platform, display_order=1)
    db_session.add(lib)
    db_session.flush()
    game = Game(library_uuid=lib.uuid, name=name, igdb_id=abs(hash(name)) % 9_000_000)
    db_session.add(game)
    db_session.commit()
    return game


@pytest.fixture
def pc_game(db_session):
    return _game_on(db_session, LibraryPlatform.PCWIN, 'PC Game')


@pytest.fixture
def snes_game(db_session):
    return _game_on(db_session, LibraryPlatform.SNES, 'SNES Game')


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


class TestSurfaceSeparation:
    def test_pc_cheat_read_requires_library_scope_for_bearer_tokens(
        self, app, db_session, pc_game,
    ):
        reader = _user(db_session, 'user')
        narrow_row, narrow_token = generate_api_token(
            reader, 'narrow pc cheat reader', ['write:presence'],
        )
        assert narrow_row.scopes == ['write:presence']
        with app.test_client() as narrow_client:
            denied = narrow_client.get(
                f'/api/games/{pc_game.uuid}/pc_cheats',
                headers={'Authorization': f'Bearer {narrow_token}'},
        )
        assert denied.status_code == 403
        assert denied.get_json()['error_code'] == 'forbidden'

    def test_pc_cheats_refused_on_a_retroarch_platform(self, client, admin_user, snes_game):
        """The PC surface must not become a second way to author .cht content."""
        _login(client, admin_user)
        response = client.get(f'/api/games/{snes_game.uuid}/pc_cheats')
        assert response.status_code == 400
        assert json.loads(response.data)['cheat_surface'] == 'retroarch'

    def test_pc_cheats_available_on_a_pc_platform(self, client, admin_user, pc_game):
        _login(client, admin_user)
        response = client.get(f'/api/games/{pc_game.uuid}/pc_cheats')
        assert response.status_code == 200
        assert json.loads(response.data)['cheats'] == []

    def test_creating_on_a_console_title_is_refused(self, client, admin_user, snes_game):
        _login(client, admin_user)
        response = client.post(
            f'/api/games/{snes_game.uuid}/pc_cheats',
            json={'label': 'Infinite lives', 'method': 'console'},
        )
        assert response.status_code == 400


class TestAuthoring:
    def test_records_a_note(self, client, app, db_session, admin_user, pc_game):
        _login(client, admin_user)
        response = client.post(
            f'/api/games/{pc_game.uuid}/pc_cheats',
            json={
                'label': 'God mode',
                'method': 'console',
                'payload': 'sv_cheats 1; god',
                'notes': 'Open console with ~',
            },
        )
        assert response.status_code == 201
        row = db.session.execute(
            db.select(PcCheat).filter_by(game_uuid=pc_game.uuid)
        ).scalars().first()
        assert row.label == 'God mode'
        assert row.payload == 'sv_cheats 1; god'
        # Single-player is the default, not something the author must remember.
        assert row.single_player_only is True

    def test_rejects_an_unknown_method(self, client, admin_user, pc_game):
        _login(client, admin_user)
        response = client.post(
            f'/api/games/{pc_game.uuid}/pc_cheats',
            json={'label': 'x', 'method': 'inject_dll'},
        )
        assert response.status_code == 400
        assert 'method must be one of' in json.loads(response.data)['error']

    def test_label_is_required(self, client, admin_user, pc_game):
        _login(client, admin_user)
        response = client.post(
            f'/api/games/{pc_game.uuid}/pc_cheats',
            json={'method': 'note'},
        )
        assert response.status_code == 422
        body = response.get_json()
        assert body['error_code'] == 'unprocessable'
        assert 'label' in body['detail']

    def test_methods_are_advertised_so_the_ui_never_hardcodes_them(self, client, admin_user, pc_game):
        _login(client, admin_user)
        body = json.loads(client.get(f'/api/games/{pc_game.uuid}/pc_cheats').data)
        ids = {m['id'] for m in body['methods']}
        assert {'console', 'config', 'save', 'launch_flag', 'note'} == ids

    def test_no_method_writes_to_a_game_binary(self, client, admin_user, pc_game):
        """The vocabulary is deliberately all 'tell the player what to do'."""
        _login(client, admin_user)
        body = json.loads(client.get(f'/api/games/{pc_game.uuid}/pc_cheats').data)
        blob = ' '.join(m['id'] + m['label'] for m in body['methods']).lower()
        for banned in ('inject', 'patch binary', 'memory write', 'trainer'):
            assert banned not in blob

    def test_delete_removes_the_row(self, client, app, db_session, admin_user, pc_game):
        _login(client, admin_user)
        created = json.loads(client.post(
            f'/api/games/{pc_game.uuid}/pc_cheats',
            json={'label': 'Noclip', 'method': 'console'},
        ).data)['cheat']

        response = client.delete(f'/api/games/{pc_game.uuid}/pc_cheats/{created["id"]}')
        assert response.status_code == 200
        assert db.session.get(PcCheat, created['id']) is None

    def test_delete_refuses_a_mismatched_game(self, client, app, db_session, admin_user, pc_game):
        """A cheat id alone must not be enough to delete across games."""
        _login(client, admin_user)
        created = json.loads(client.post(
            f'/api/games/{pc_game.uuid}/pc_cheats',
            json={'label': 'Noclip', 'method': 'console'},
        ).data)['cheat']

        other = _game_on(db_session, LibraryPlatform.PCDOS, 'Other PC Game')
        response = client.delete(f'/api/games/{other.uuid}/pc_cheats/{created["id"]}')
        assert response.status_code == 404
        assert db.session.get(PcCheat, created['id']) is not None
