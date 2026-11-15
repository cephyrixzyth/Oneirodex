"""Qualify only the disposable Windows user fixture; never install an app."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import uuid

from windows_user_fixture import FixtureFailure, StandardUserFixture, require_fixture_ci, safe_fixture_diagnostic


def run_control(work, progress, factory=None):
    progress.update(native_fixture_qualified=False, installed_runtime_acceptance=False,
                    cleanup_verified=False, phase='fixture_provisioning')
    context = (factory or StandardUserFixture.open)(work)
    marker, body_error = None, None
    content = b'Oneirodex owned CLI profile fixture; not a registered game or save.\n'
    try:
        for field in ('standard_user_verified', 'profile_environment_verified', 'private_desktop_created'):
            if context.receipt.get(field) is not True:
                raise FixtureFailure('fixture_control_prerequisite_not_verified')
            progress[field] = True
        progress['cli_exit_codes'] = []
        profile = Path(context.profile_root).resolve(strict=True)
        for round_number, expected in enumerate((37, 38), 1):
            progress['phase'] = 'cli_round_' + str(round_number)
            child = context.start(context.api.bootstrap_executable(), context.environment,
                                  ['/d', '/c', 'exit', str(expected)])
            child_error = None
            try:
                actual = child.wait(20)
                if actual != expected:
                    raise FixtureFailure('fixture_control_exit_mismatch')
                progress['cli_exit_codes'].append(actual)
            except BaseException as error:
                child_error = error
                raise
            finally:
                try:
                    child.close()
                except Exception:
                    if child_error is None:
                        raise
                    child_error.add_note('fixture_child_cleanup_failed')
            if round_number == 1:
                marker = profile / ('oneirodex-cli-' + uuid.uuid4().hex + '.txt')
                with marker.open('xb') as output:
                    output.write(content)
            elif (Path(context.profile_root).resolve(strict=True) != profile
                  or not marker.is_file() or marker.read_bytes() != content):
                raise FixtureFailure('fixture_control_profile_marker_changed')
        progress['owned_profile_marker_retained_between_cli_rounds'] = True
    except BaseException as error:
        body_error = error
        raise
    finally:
        cleanup_error = None
        if marker is not None:
            try:
                if marker.read_bytes() != content:
                    raise FixtureFailure('fixture_control_marker_cleanup_failed')
                marker.unlink()
                progress['owned_marker_removed'] = True
            except Exception as error:
                cleanup_error = error
                progress['owned_marker_removed'] = False
        try:
            context.close()
        except Exception as error:
            cleanup_error = cleanup_error or error
        progress['cleanup_verified'] = context.receipt.get('cleanup_verified') is True and cleanup_error is None
        errors = context.receipt.get('cleanup_errors', [])
        progress['cleanup_errors'] = [code for code in errors[:12]
                                      if isinstance(code, str) and re.fullmatch(r'fixture_[a-z0-9_]{1,100}', code)]
        if cleanup_error is not None:
            if not progress['cleanup_errors']:
                progress['cleanup_errors'] = ['fixture_cleanup_failed']
            if body_error is None:
                raise FixtureFailure('fixture_control_cleanup_failed') from None
            body_error.add_note('fixture_cleanup_failed')
    if not progress['cleanup_verified']:
        raise FixtureFailure('fixture_control_cleanup_not_verified')
    progress.update(native_fixture_qualified=True, phase='complete')
    return progress


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--work-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    receipt = {'observed_utc': datetime.now(timezone.utc).isoformat(), 'status': 'failed',
               'native_fixture_qualified': False, 'installed_runtime_acceptance': False}
    try:
        require_fixture_ci()
        if not args.execute:
            raise FixtureFailure('fixture_execution_not_requested')
        run_control(args.work_dir, receipt)
        receipt['status'] = 'fixture-qualified'
        code = 0
    except FixtureFailure as error:
        receipt['code'] = str(error)
        details = safe_fixture_diagnostic(getattr(error, 'diagnostic', None))
        if details:
            receipt['diagnostic'] = details
        if getattr(error, 'cleanup_verified', None) is True:
            receipt['cleanup_verified'] = True
        code = 2 if str(error) in ('execution_requires_disposable_windows_ci',
                                  'fixture_execution_not_requested') else 1
        if code == 2:
            receipt['status'] = 'unsupported'
    except Exception as error:
        receipt.update(code='fixture_control_failed', error_class=type(error).__name__)
        code = 1
    print(json.dumps(receipt, indent=2))
    return code


if __name__ == '__main__':
    sys.exit(main())
