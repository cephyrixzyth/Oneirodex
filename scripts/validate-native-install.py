"""Validate native runtime configuration and required source-built SPA assets."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from oneirodex.runtime_native.app_config import build_runtime_config
from oneirodex.runtime_native.runtime_context import NativeRuntimeContext


PACKAGE_ROOT = ROOT / 'oneirodex'
SPA_TARGETS = {
    'member-app': 'index.html',
    'member-auth': 'auth.html',
    'admin-app': 'index.html',
    'admin-pilot': 'index.html',
    'ops-glance': 'index.html',
}


def main() -> int:
    missing = [
        target
        for target, entry in SPA_TARGETS.items()
        if not (PACKAGE_ROOT / 'static' / 'dist' / target / entry).is_file()
    ]
    if missing:
        print(f"Missing built SPA entry points: {', '.join(missing)}")
        return 1

    runtime_config = build_runtime_config(package_root=PACKAGE_ROOT)
    runtime = NativeRuntimeContext(runtime_config, package_root=PACKAGE_ROOT)
    if Path(runtime.static_folder).resolve() != (PACKAGE_ROOT / 'static').resolve():
        print('Native runtime static root does not resolve to the application package.')
        return 1

    print(f'Native runtime configuration and {len(SPA_TARGETS)} SPA assets validated.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
