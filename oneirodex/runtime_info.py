"""Framework-independent process metadata shared by ASGI and compatibility code."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path


def _read_version() -> str:
    """Read the product version from the single tracked source of truth."""
    version_file = Path(__file__).resolve().parent.parent / 'VERSION'
    try:
        value = version_file.read_text(encoding='utf-8').strip()
        return value or '1.1.9'
    except OSError:
        return '1.1.9'


app_version = _read_version()
app_start_time = datetime.now()


__all__ = ['app_start_time', 'app_version']
