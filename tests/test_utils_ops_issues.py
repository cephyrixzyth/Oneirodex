# tests/test_utils_ops_issues.py
from oneirodex.utils.ops_issues import derive_issues


def test_good_when_healthy():
    result = derive_issues(
        disk_base_percent=40,
        disk_games_percent=50,
        path_problems=[],
        scan_failures=0,
        recent_error_count=0,
    )
    assert result['overall'] == 'good'
    assert result['items'] == []


def test_warn_at_85_percent_disk():
    result = derive_issues(
        disk_base_percent=85,
        disk_games_percent=10,
        path_problems=[],
        scan_failures=0,
        recent_error_count=0,
    )
    assert result['overall'] == 'good'
    item = next(i for i in result['items'] if i['id'] == 'disk_base_high')
    assert item['severity'] == 'info'
    assert item['category'] == 'info'


def test_disk_critical_percent_is_info_not_warn_or_bad():
    """Space running out is capacity info — never warning/action alone."""
    result = derive_issues(
        disk_base_percent=10,
        disk_games_percent=99,
        path_problems=[],
        scan_failures=0,
        recent_error_count=0,
    )
    assert result['overall'] == 'good'
    assert result['overall'] != 'bad'
    item = next(i for i in result['items'] if i['id'] == 'disk_games_critical')
    assert item['severity'] == 'info'
    assert item['category'] == 'info'
    assert all(i['severity'] != 'bad' for i in result['items'])
    assert all(i['category'] != 'action' for i in result['items'])
    assert all(i['severity'] != 'warn' for i in result['items'])


def test_path_problem_is_bad_action():
    result = derive_issues(
        disk_base_percent=10,
        disk_games_percent=10,
        path_problems=[{'key': 'DATA_FOLDER_GAMES', 'reason': 'missing'}],
        scan_failures=0,
        recent_error_count=0,
    )
    assert result['overall'] == 'bad'
    item = next(i for i in result['items'] if i['id'] == 'path_DATA_FOLDER_GAMES')
    assert item['severity'] == 'bad'
    assert item['category'] == 'action'


def test_disk_full_plus_path_still_bad():
    """Path failure forces action; disk pressure alone does not."""
    result = derive_issues(
        disk_base_percent=99,
        disk_games_percent=99,
        path_problems=[{'key': 'DATA_FOLDER_GAMES', 'reason': 'missing'}],
        scan_failures=0,
        recent_error_count=0,
    )
    assert result['overall'] == 'bad'
    assert any(i['category'] == 'action' for i in result['items'])
    assert any(i['id'].startswith('disk_') and i['severity'] == 'info' for i in result['items'])


def test_recent_errors_warn():
    result = derive_issues(
        disk_base_percent=10,
        disk_games_percent=10,
        path_problems=[],
        scan_failures=0,
        recent_error_count=2,
    )
    assert result['overall'] == 'warn'
    item = next(i for i in result['items'] if i['id'] == 'recent_errors')
    assert item['category'] == 'warning'


def test_scan_failures_are_warn_not_bad():
    result = derive_issues(
        disk_base_percent=10,
        disk_games_percent=10,
        path_problems=[],
        scan_failures=3,
        recent_error_count=0,
    )
    assert result['overall'] == 'warn'
    item = next(i for i in result['items'] if i['id'] == 'scan_failures')
    assert item['severity'] == 'warn'
    assert item['category'] == 'warning'


def test_db_unreachable_is_action():
    result = derive_issues(
        disk_base_percent=10,
        disk_games_percent=10,
        path_problems=[],
        scan_failures=0,
        recent_error_count=0,
        db_reachable=False,
    )
    assert result['overall'] == 'bad'
    item = next(i for i in result['items'] if i['id'] == 'db_unreachable')
    assert item['category'] == 'action'


def test_awake_fail_is_action():
    result = derive_issues(
        disk_base_percent=10,
        disk_games_percent=10,
        path_problems=[],
        scan_failures=0,
        recent_error_count=0,
        awake_ok=False,
    )
    assert result['overall'] == 'bad'
    item = next(i for i in result['items'] if i['id'] == 'awake_fail')
    assert item['severity'] == 'bad'
    assert item['category'] == 'action'


def test_companions_stale_is_info_not_action():
    result = derive_issues(
        disk_base_percent=10,
        disk_games_percent=10,
        path_problems=[],
        scan_failures=0,
        recent_error_count=0,
        companions_stale=2,
    )
    assert result['overall'] == 'good'
    item = next(i for i in result['items'] if i['id'] == 'companions_stale')
    assert item['severity'] == 'info'
    assert item['category'] == 'info'


def test_livekit_enabled_configuration_problems_are_warnings():
    base = {
        'disk_base_percent': 10,
        'disk_games_percent': 10,
        'path_problems': [],
        'scan_failures': 0,
        'recent_error_count': 0,
    }
    incomplete = derive_issues(
        **base,
        livekit={'enabled': True, 'configured': False, 'reachable': None},
    )
    assert incomplete['overall'] == 'warn'
    assert next(i for i in incomplete['items'] if i['id'] == 'livekit_incomplete_config')['severity'] == 'warn'

    unreachable = derive_issues(
        **base,
        livekit={'enabled': True, 'configured': True, 'reachable': False},
    )
    assert unreachable['overall'] == 'warn'
    assert next(i for i in unreachable['items'] if i['id'] == 'livekit_unreachable')['severity'] == 'warn'


def test_livekit_disabled_or_unknown_fields_do_not_create_issues():
    base = {
        'disk_base_percent': 10,
        'disk_games_percent': 10,
        'path_problems': [],
        'scan_failures': 0,
        'recent_error_count': 0,
    }
    for livekit in (
        {'enabled': False, 'configured': False, 'reachable': None},
        {'enabled': None, 'configured': None, 'reachable': None},
        {'enabled': True, 'configured': True, 'reachable': None},
        {},
        None,
    ):
        result = derive_issues(**base, livekit=livekit)
        assert result == {'overall': 'good', 'items': []}
