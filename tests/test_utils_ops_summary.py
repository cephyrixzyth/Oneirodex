from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _host_patches(**overrides):
    """Common host/network/library mocks for build_ops_summary tests."""
    defaults = {
        'get_cpu_usage': {'percent': 1, 'cores_physical': 2, 'cores_logical': 4},
        'get_memory_usage': {'total': 8, 'used': 4, 'available': 4, 'percent': 50},
        'get_disk_usage': {'total': 1, 'used': 1, 'free': 0, 'percent': 40},
        'get_games_folder_usage': {'total': 1, 'used': 1, 'free': 0, 'percent': 40},
        'get_system_info': {
            'Operating System': 'Linux',
            'Hostname': 'h',
            'IP Address': '1.2.3.4',
            'Python Version': '3.12',
        },
        'get_config_values': {},
        'get_formatted_system_uptime': '1h',
        'get_formatted_app_uptime': '1h',
        'get_load_average': {'1': 0.5, '5': 0.4, '15': 0.3},
        'get_process_memory': {'pid': 42, 'rss_bytes': 1048576},
        '_db_ping_ms': 1.25,
        'get_network_stats': {
            'bytes_sent': 0,
            'bytes_recv': 0,
            'packets_sent': 0,
            'packets_recv': 0,
            'errin': 0,
            'errout': 0,
            'dropin': 0,
            'dropout': 0,
            'connections': 0,
        },
        '_library_pulse': {
            'libraries': 1,
            'games': 2,
            'unmatched_folders': 0,
            'download_requests_open': 0,
        },
        '_scan_snapshot': {
            'active_count': 0,
            'queued_count': 0,
            'jobs': [],
            'failure_count': 0,
        },
        '_recent_errors': ([], 0),
        '_services_snapshot': {
            'livekit': {'enabled': False, 'configured': False, 'reachable': None},
            'malware': {'enabled': True, 'clamav_reachable': False},
            'companions': {
                'online': 0,
                'registered': 0,
                'window_minutes': 3,
                'by_kind': {},
                'last_seen': {
                    'newest': None,
                    'within_1h': 0,
                    'within_24h': 0,
                    'stale': 0,
                },
            },
            'queues': {
                'scans_active': 0,
                'scans_pending': 0,
                'scans_queued': 0,
                'scans_scheduled': 0,
                'scans_failures_24h': 0,
                'downloads_open': 0,
            },
            'awake': {
                'status': 'ok',
                'http_status': 200,
                'checks': {'database': {'ok': True, 'error': None}},
                'check_ms': 2.0,
            },
            'malware_module_enabled': True,
        },
    }
    defaults.update(overrides)
    return defaults


def test_build_ops_summary_includes_required_keys():
    values = _host_patches()
    with patch(
        'oneirodex.utils.ops_summary.get_cpu_usage',
        return_value=values['get_cpu_usage'],
    ) as get_cpu_usage, patch(
        'oneirodex.utils.ops_summary.get_memory_usage',
        return_value=values['get_memory_usage'],
    ), patch(
        'oneirodex.utils.ops_summary.get_disk_usage',
        return_value=values['get_disk_usage'],
    ), patch(
        'oneirodex.utils.ops_summary.get_games_folder_usage',
        return_value=values['get_games_folder_usage'],
    ), patch(
        'oneirodex.utils.ops_summary.get_system_info',
        return_value=values['get_system_info'],
    ), patch(
        'oneirodex.utils.ops_summary.get_config_values',
        return_value=values['get_config_values'],
    ), patch(
        'oneirodex.utils.ops_summary.get_formatted_system_uptime',
        return_value=values['get_formatted_system_uptime'],
    ), patch(
        'oneirodex.utils.ops_summary.get_formatted_app_uptime',
        return_value=values['get_formatted_app_uptime'],
    ), patch(
        'oneirodex.utils.ops_summary.get_load_average',
        return_value=values['get_load_average'],
    ), patch(
        'oneirodex.utils.ops_summary.get_process_memory',
        return_value=values['get_process_memory'],
    ), patch(
        'oneirodex.utils.ops_summary._db_ping_ms',
        return_value=values['_db_ping_ms'],
    ), patch(
        'oneirodex.utils.ops_summary.get_network_stats',
        return_value=values['get_network_stats'],
    ), patch(
        'oneirodex.utils.ops_summary._library_pulse',
        return_value=values['_library_pulse'],
    ), patch(
        'oneirodex.utils.ops_summary._scan_snapshot',
        return_value=values['_scan_snapshot'],
    ), patch(
        'oneirodex.utils.ops_summary._recent_errors',
        return_value=values['_recent_errors'],
    ), patch(
        'oneirodex.utils.ops_summary._services_snapshot',
        return_value=values['_services_snapshot'],
    ):
        from oneirodex.utils.ops_summary import build_ops_summary

        result = build_ops_summary(datetime.now(timezone.utc))

    assert set(result.keys()) >= {
        'as_of',
        'host',
        'network',
        'issues',
        'scans',
        'library',
        'services',
        'recent_errors',
    }
    assert result['services']['companions']['online'] == 0
    assert result['host']['cpu']['cores_logical'] == 4
    assert result['host']['load_avg'] == {'1': 0.5, '5': 0.4, '15': 0.3}
    assert result['host']['process'] == {'pid': 42, 'rss_bytes': 1048576}
    assert result['host']['db_ping_ms'] == 1.25
    assert result['services']['awake']['status'] == 'ok'
    assert result['issues']['overall'] == 'good'
    assert set(result['issues'].keys()) == {'overall', 'items'}
    assert isinstance(result['issues']['items'], list)
    get_cpu_usage.assert_called_once_with()


def test_awake_pulse_passes_native_config_to_readiness():
    from oneirodex.utils.ops_summary import _awake_pulse

    config = {'TESTING': False, 'ONEIRODEX_INIT_COMPLETE': True}
    with patch(
        'oneirodex.utils.ops_summary.build_readiness',
        return_value=({'status': 'ok', 'checks': {'database': {'ok': True}}}, 200),
    ) as readiness:
        result = _awake_pulse(config=config)

    readiness.assert_called_once_with(config=config)
    assert result['status'] == 'ok'
    assert result['http_status'] == 200


def test_build_ops_summary_host_enrichment_none_when_unavailable():
    values = _host_patches(
        get_load_average=None,
        get_process_memory=None,
        _db_ping_ms=None,
    )
    with patch(
        'oneirodex.utils.ops_summary.get_cpu_usage',
        return_value=values['get_cpu_usage'],
    ), patch(
        'oneirodex.utils.ops_summary.get_memory_usage',
        return_value=values['get_memory_usage'],
    ), patch(
        'oneirodex.utils.ops_summary.get_disk_usage',
        return_value=values['get_disk_usage'],
    ), patch(
        'oneirodex.utils.ops_summary.get_games_folder_usage',
        return_value=values['get_games_folder_usage'],
    ), patch(
        'oneirodex.utils.ops_summary.get_system_info',
        return_value=values['get_system_info'],
    ), patch(
        'oneirodex.utils.ops_summary.get_config_values',
        return_value=values['get_config_values'],
    ), patch(
        'oneirodex.utils.ops_summary.get_formatted_system_uptime',
        return_value=values['get_formatted_system_uptime'],
    ), patch(
        'oneirodex.utils.ops_summary.get_formatted_app_uptime',
        return_value=values['get_formatted_app_uptime'],
    ), patch(
        'oneirodex.utils.ops_summary.get_load_average',
        return_value=None,
    ), patch(
        'oneirodex.utils.ops_summary.get_process_memory',
        return_value=None,
    ), patch(
        'oneirodex.utils.ops_summary._db_ping_ms',
        return_value=None,
    ), patch(
        'oneirodex.utils.ops_summary.get_network_stats',
        return_value=values['get_network_stats'],
    ), patch(
        'oneirodex.utils.ops_summary._library_pulse',
        return_value=values['_library_pulse'],
    ), patch(
        'oneirodex.utils.ops_summary._scan_snapshot',
        return_value=values['_scan_snapshot'],
    ), patch(
        'oneirodex.utils.ops_summary._recent_errors',
        return_value=values['_recent_errors'],
    ), patch(
        'oneirodex.utils.ops_summary._services_snapshot',
        return_value={
            **values['_services_snapshot'],
            'awake': None,
        },
    ):
        from oneirodex.utils.ops_summary import build_ops_summary

        result = build_ops_summary(datetime.now(timezone.utc))

    assert result['host']['load_avg'] is None
    assert result['host']['process'] is None
    assert result['host']['db_ping_ms'] is None
    assert result['services']['awake'] is None
    # Not 'good'. `load_avg`/`process` really are optional enrichment and are
    # ignored, but a missing db_ping is read as "database unreachable" and a
    # missing awake as "readiness unknown" — both feed derive_issues now, and
    # calling that healthy would be the summary lying about a down database.
    assert result['issues']['overall'] == 'bad'


def test_scan_snapshot_counts_active_folder_failures():
    last_update = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
    active_job = SimpleNamespace(
        id='abcdef12-3456-7890-abcd-ef1234567890',
        library=SimpleNamespace(name='Games'),
        status='Running',
        total_folders=4,
        folders_success=1,
        folders_failed=2,
        current_processing='Processing: Halo (3/4)',
        last_progress_update=last_update,
        # _scan_job_payload reads this like its siblings (GT-B38); a stub
        # standing in for a ScanJob has to carry the fields the payload reads.
        error_message=None,
    )
    active_result = MagicMock()
    active_result.scalars.return_value.all.return_value = [active_job]
    queued_result = MagicMock()
    queued_result.scalars.return_value.all.return_value = []
    recent_result = MagicMock()
    recent_result.scalars.return_value.all.return_value = []
    failure_result = MagicMock()
    failure_result.scalar.return_value = 3

    with patch(
        'oneirodex.utils.ops_summary.db.session.execute',
        side_effect=(active_result, queued_result, recent_result, failure_result),
    ) as execute:
        from oneirodex.utils.ops_summary import _scan_snapshot

        result = _scan_snapshot()

    failure_query = str(execute.call_args_list[3].args[0])
    assert 'folders_failed >' in failure_query
    job = result['jobs'][0]
    assert job['errors'] == 2
    assert job['folders_failed'] == 2
    assert job['folders_success'] == 1
    assert job['total_folders'] == 4
    assert job['status'] == 'Running'
    assert job['id_short'] == 'abcdef12'
    assert job['current_processing'] == 'Processing: Halo (3/4)'
    assert job['last_progress_update'] == last_update.isoformat()
    assert job['library'] == 'Games'
    assert job['progress'] == 75
    assert result['active_count'] == 1
    assert result['queued_count'] == 0
    assert result['failure_count'] == 3


def test_scan_snapshot_includes_recent_terminal_jobs():
    completed = SimpleNamespace(
        id='deadbeef-0000-0000-0000-000000000001',
        library=SimpleNamespace(name='PC'),
        status='Completed',
        total_folders=10,
        folders_success=9,
        folders_failed=1,
        current_processing=None,
        last_progress_update=datetime(2026, 7, 27, 11, 0, tzinfo=timezone.utc),
        error_message=None,
    )
    active_result = MagicMock()
    active_result.scalars.return_value.all.return_value = []
    queued_result = MagicMock()
    queued_result.scalars.return_value.all.return_value = []
    recent_result = MagicMock()
    recent_result.scalars.return_value.all.return_value = [completed]
    failure_result = MagicMock()
    failure_result.scalar.return_value = 0

    with patch(
        'oneirodex.utils.ops_summary.db.session.execute',
        side_effect=(active_result, queued_result, recent_result, failure_result),
    ):
        from oneirodex.utils.ops_summary import _scan_snapshot

        result = _scan_snapshot()

    assert result['active_count'] == 0
    assert result['queued_count'] == 0
    assert len(result['jobs']) == 1
    job = result['jobs'][0]
    assert job['status'] == 'Completed'
    assert job['id_short'] == 'deadbeef'
    assert job['folders_success'] == 9
    assert job['folders_failed'] == 1
    assert job['total_folders'] == 10
    assert job['progress'] == 100


def test_build_ops_summary_keeps_other_sections_on_network_failure():
    values = _host_patches()
    with patch(
        'oneirodex.utils.ops_summary.get_cpu_usage',
        return_value=values['get_cpu_usage'],
    ), patch(
        'oneirodex.utils.ops_summary.get_memory_usage',
        return_value=values['get_memory_usage'],
    ), patch(
        'oneirodex.utils.ops_summary.get_disk_usage',
        return_value=values['get_disk_usage'],
    ), patch(
        'oneirodex.utils.ops_summary.get_games_folder_usage',
        return_value=values['get_games_folder_usage'],
    ), patch(
        'oneirodex.utils.ops_summary.get_system_info',
        return_value=values['get_system_info'],
    ), patch(
        'oneirodex.utils.ops_summary.get_config_values',
        return_value=values['get_config_values'],
    ), patch(
        'oneirodex.utils.ops_summary.get_formatted_system_uptime',
        return_value=values['get_formatted_system_uptime'],
    ), patch(
        'oneirodex.utils.ops_summary.get_formatted_app_uptime',
        return_value=values['get_formatted_app_uptime'],
    ), patch(
        'oneirodex.utils.ops_summary.get_load_average',
        return_value=values['get_load_average'],
    ), patch(
        'oneirodex.utils.ops_summary.get_process_memory',
        return_value=values['get_process_memory'],
    ), patch(
        'oneirodex.utils.ops_summary._db_ping_ms',
        return_value=values['_db_ping_ms'],
    ), patch(
        'oneirodex.utils.ops_summary.get_network_stats',
        side_effect=RuntimeError('secret connection string'),
    ), patch(
        'oneirodex.utils.ops_summary._library_pulse',
        return_value=values['_library_pulse'],
    ), patch(
        'oneirodex.utils.ops_summary._scan_snapshot',
        return_value=values['_scan_snapshot'],
    ), patch(
        'oneirodex.utils.ops_summary._recent_errors',
        return_value=values['_recent_errors'],
    ), patch(
        'oneirodex.utils.ops_summary._services_snapshot',
        return_value=values['_services_snapshot'],
    ):
        from oneirodex.utils.ops_summary import build_ops_summary

        result = build_ops_summary(datetime.now(timezone.utc))

    assert result['network'] is None
    assert result['network_error'] == 'Network data unavailable'
    assert 'secret connection string' not in result['network_error']
    assert result['host']['hostname'] == 'h'
    assert result['host']['db_ping_ms'] == 1.25
    assert result['scans'] == {'active_count': 0, 'jobs': []}
    assert result['library']['games'] == 2
    assert result['services']['companions']['online'] == 0
    assert result['recent_errors'] == []


def test_db_ping_ms_returns_none_on_failure():
    with patch(
        'oneirodex.utils.ops_summary.db.session.execute',
        side_effect=RuntimeError('db down'),
    ):
        from oneirodex.utils.ops_summary import _db_ping_ms

        assert _db_ping_ms() is None


def test_db_ping_ms_returns_latency():
    with patch('oneirodex.utils.ops_summary.db.session.execute', return_value=None):
        from oneirodex.utils.ops_summary import _db_ping_ms

        ms = _db_ping_ms()
    assert isinstance(ms, float)
    assert ms >= 0


def test_awake_pulse_includes_timing_and_checks():
    payload = {
        'status': 'ok',
        'probe': 'readiness',
        'checks': {
            'database': {'ok': True, 'error': None},
            'initialization': {'ok': True, 'complete': True, 'testing_bypass': False},
        },
    }
    with patch(
        'oneirodex.utils.ops_summary.build_readiness',
        return_value=(payload, 200),
    ):
        from oneirodex.utils.ops_summary import _awake_pulse

        result = _awake_pulse()

    assert result['status'] == 'ok'
    assert result['http_status'] == 200
    assert result['checks']['database']['ok'] is True
    assert isinstance(result['check_ms'], float)
    assert result['check_ms'] >= 0


def test_awake_pulse_none_when_unavailable():
    with patch(
        'oneirodex.utils.ops_summary.build_readiness',
        side_effect=RuntimeError('no app'),
    ):
        from oneirodex.utils.ops_summary import _awake_pulse

        assert _awake_pulse() is None


def test_malware_pulse_preserves_unknown_source_fields(monkeypatch):
    from oneirodex.utils import ops_summary

    monkeypatch.setattr(ops_summary, 'module_status', lambda: {'clamav': {}})
    assert ops_summary._malware_pulse() == {
        'enabled': None,
        'block_on_hit': None,
        'clamav_reachable': None,
        'clamav_version': None,
        'clamav_error': None,
        'heuristics': {},
    }


def test_malware_pulse_preserves_explicit_false_values(monkeypatch):
    from oneirodex.utils import ops_summary

    monkeypatch.setattr(
        ops_summary,
        'module_status',
        lambda: {
            'enabled': False,
            'block_on_hit': False,
            'clamav': {'available': False},
        },
    )
    result = ops_summary._malware_pulse()
    assert result['enabled'] is False
    assert result['block_on_hit'] is False
    assert result['clamav_reachable'] is False


def test_companion_pulse_last_seen_breakdown():
    newest = datetime(2026, 7, 28, 18, 0, tzinfo=timezone.utc)
    scalars = [
        MagicMock(scalar=MagicMock(return_value=1)),  # online
        MagicMock(scalar=MagicMock(return_value=3)),  # registered
        MagicMock(scalar=MagicMock(return_value=2)),  # within_1h
        MagicMock(scalar=MagicMock(return_value=3)),  # within_24h
        MagicMock(scalar=MagicMock(return_value=newest)),  # newest
        MagicMock(all=MagicMock(return_value=[('companion', 2), ('thin', 1)])),
        MagicMock(all=MagicMock(return_value=[('companion', 1)])),
    ]

    def _execute(_stmt):
        return scalars.pop(0)

    with patch(
        'oneirodex.utils.ops_summary.db.session.execute',
        side_effect=_execute,
    ):
        from oneirodex.utils.ops_summary import _companion_pulse

        result = _companion_pulse()

    assert result['online'] == 1
    assert result['registered'] == 3
    assert result['window_minutes'] == 3
    assert result['by_kind'] == {
        'companion': {'registered': 2, 'online': 1},
        'thin': {'registered': 1, 'online': 0},
    }
    assert result['last_seen'] == {
        'newest': newest.isoformat(),
        'within_1h': 2,
        'within_24h': 3,
        'stale': 2,
    }


def test_get_load_average_none_when_unavailable():
    import oneirodex.utils.system_stats as stats_mod

    with patch.object(
        stats_mod.os,
        'getloadavg',
        create=True,
        side_effect=OSError('no loadavg'),
    ):
        assert stats_mod.get_load_average() is None


def test_get_load_average_returns_values_when_available():
    import oneirodex.utils.system_stats as stats_mod

    with patch.object(
        stats_mod.os,
        'getloadavg',
        create=True,
        return_value=(0.12, 0.34, 0.56),
    ):
        assert stats_mod.get_load_average() == {'1': 0.12, '5': 0.34, '15': 0.56}


def test_get_process_memory_none_when_unavailable():
    with patch(
        'oneirodex.utils.system_stats.psutil.Process',
        side_effect=RuntimeError('denied'),
    ):
        from oneirodex.utils.system_stats import get_process_memory

        assert get_process_memory() is None
