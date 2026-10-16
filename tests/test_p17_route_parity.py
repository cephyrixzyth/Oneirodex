from scripts.p17_route_parity import _path_covers


def test_native_dynamic_path_covers_static_flask_route():
    assert _path_covers(
        '/api/ownership/{store}/csv', {'store': 'string'},
        '/api/ownership/steam/csv', {},
    )


def test_static_native_route_does_not_claim_dynamic_legacy_coverage():
    assert not _path_covers(
        '/api/games/specific-game', {},
        '/api/games/{game_id}', {'game_id': 'string'},
    )


def test_native_path_converter_must_cover_legacy_converter_domain():
    assert _path_covers(
        '/api/users/{user_id}', {'user_id': 'string'},
        '/api/users/{user_id}', {'user_id': 'integer'},
    )
    assert not _path_covers(
        '/api/users/{user_id}', {'user_id': 'integer'},
        '/api/users/{user_id}', {'user_id': 'string'},
    )
