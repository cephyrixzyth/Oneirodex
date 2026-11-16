"""Linux package lifecycle policy, independent of native API implementation."""
from pathlib import Path
import uuid

from probe_linux_packaged import ProbeFailure


def runtime_environment(work, ignored_parent=None):
    return {'PATH': '/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8',
            'HOME': str(work/'home'), 'XDG_CONFIG_HOME': str(work/'config'),
            'XDG_DATA_HOME': str(work/'data'), 'XDG_CACHE_HOME': str(work/'cache'),
            'XDG_RUNTIME_DIR': str(work/'runtime'), 'TMPDIR': str(work/'tmp')}


def execute_probe(deb, work, progress, native=None, journey=None):
    progress.update(installed_runtime_acceptance=False, cleanup_verified=False, cold_rounds=[])
    if native is None:
        from linux_packaged_native import NativeLinuxAPI
        native = NativeLinuxAPI(work, progress)
    if native.present():
        raise ProbeFailure('foreign_linux_package_already_present')
    marker, body_error, attempted = None, None, False
    content = b'Oneirodex CI owned retention marker; not a game save.\n'
    try:
        progress['phase'] = 'linux_package_install'
        attempted = True
        native.install(deb)
        progress['installer_executed'] = True
        native.verify_binary()
        native.start_context()
        if journey is not None:
            native.start_secret_service()
        for number in (1, 2):
            progress['phase'] = 'linux_cold_round_' + str(number)
            round_error = None
            try:
                directory, checks = native.round(number)
                required = ('bundled_renderer', 'native_ipc', 'parent_directory_denied',
                            'ordinary_user', 'listener_ownership_verified')
                if not all(checks.get(key) is True for key in required):
                    raise ProbeFailure('linux_native_round_not_verified')
                directory = Path(directory).resolve(strict=True)
                data_root = Path(native.data_root).resolve(strict=True)
                if directory == data_root or not directory.is_relative_to(data_root) or not directory.is_dir():
                    raise ProbeFailure('linux_installs_directory_not_owned')
                native.app_directory=directory.parent
                progress['cold_rounds'].append({'round': number, **{key: True for key in required}})
            except BaseException as error:
                round_error = error
                raise
            finally:
                try:
                    native.stop_round()
                except Exception:
                    if round_error is None:
                        raise
                    round_error.add_note('linux_round_cleanup_failed')
            if number == 1:
                marker = directory / ('oneirodex-ci-' + uuid.uuid4().hex + '.txt')
                with marker.open('xb') as output:
                    output.write(content)
            elif marker.parent != directory or marker.read_bytes() != content:
                raise ProbeFailure('linux_reopen_marker_changed')
        progress['owned_marker_retained_after_cold_reopen'] = True
        if journey is not None:
            progress['phase'] = 'linux_connected_account_journey'
            journey(native, progress)
    except BaseException as error:
        body_error = error
        raise
    finally:
        cleanup_errors = []
        context_stopped = False
        try:
            native.stop_context()
            context_stopped = True
        except Exception:
            cleanup_errors.append('linux_context_cleanup_failed')
        if attempted and context_stopped:
            try:
                native.uninstall()
                if not native.absent():
                    raise ProbeFailure('linux_package_not_removed')
                progress['owned_package_uninstalled'] = True
                if marker is not None:
                    if marker.read_bytes() != content:
                        raise ProbeFailure('linux_uninstall_marker_changed')
                    progress['owned_marker_retained_after_uninstall'] = True
                    marker.unlink()
                    progress['owned_marker_removed'] = True
            except Exception:
                cleanup_errors.append('linux_package_or_marker_cleanup_failed')
        progress.update(cleanup_verified=not cleanup_errors, cleanup_errors=cleanup_errors)
        if cleanup_errors:
            if body_error is None:
                raise ProbeFailure(cleanup_errors[0])
            for code in cleanup_errors:
                body_error.add_note(code)
    progress.update(installed_runtime_acceptance=True, phase='complete')
