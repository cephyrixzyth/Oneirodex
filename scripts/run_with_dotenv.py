"""Load native configuration as data, then replace this process with its launcher."""
from io import StringIO
import os
from pathlib import Path
import re
import sys


ENV_READY = 'ONEIRODEX_NATIVE_DOTENV_READY'
ENV_NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_]*\Z')
SHELL_STARTUP_NAMES = {'BASH_ENV', 'SHELLOPTS', 'BASHOPTS'}


def environment_from_file(path: Path) -> dict[str, str]:
    # Import after entering main's error boundary: a broken venv must not dump
    # import paths or leave startup running with only part of its configuration.
    from dotenv import dotenv_values
    from dotenv.parser import parse_stream

    text = path.read_text(encoding='utf-8-sig')
    if '\0' in text or any(binding.error for binding in parse_stream(StringIO(text))):
        raise ValueError('Invalid dotenv input')
    values = dotenv_values(stream=StringIO(text))
    environment = dict(os.environ)
    for key, value in values.items():
        if not ENV_NAME.fullmatch(key) or key in SHELL_STARTUP_NAMES:
            raise ValueError('Invalid environment name')
        if value is not None:
            environment[key] = value
    environment[ENV_READY] = str(os.getpid())
    return environment


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        sys.stderr.write('A native launcher is required.\n')
        return 2
    try:
        environment = environment_from_file(Path('.env'))
        os.execvpe('bash', ['bash', *argv], environment)
    except (ImportError, OSError, ValueError):
        sys.stderr.write('Unable to load native configuration. Check .env and the virtual-environment dependencies.\n')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
