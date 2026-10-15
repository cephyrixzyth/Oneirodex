"""Framework-independent validation for uploaded theme files and names."""
from __future__ import annotations

from typing import Optional


MAX_THEME_FILE_SIZE = 25 * 1024 * 1024
ZIP_MAGIC_BYTES = (b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08')
WINDOWS_RESERVED_NAMES = frozenset({
    'CON', 'PRN', 'AUX', 'NUL',
    'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
    'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9',
})


def validate_theme_file(file) -> tuple[bool, Optional[str]]:
    if not file or not file.filename:
        return False, 'No file provided'
    file.seek(0, 2)
    file_size = file.tell()
    file.seek(0)
    if file_size > MAX_THEME_FILE_SIZE:
        return False, f'File size ({file_size / (1024*1024):.1f}MB) exceeds maximum allowed size (25MB)'
    if file_size == 0:
        return False, 'File is empty'
    file_header = file.read(4)
    file.seek(0)
    if not any(file_header.startswith(magic) for magic in ZIP_MAGIC_BYTES):
        return False, 'File is not a valid ZIP archive'
    return True, None


def is_valid_theme_name(name: str) -> tuple[bool, Optional[str]]:
    if not name or not name.strip():
        return False, 'Theme name cannot be empty'
    name_upper = name.upper()
    if name_upper in WINDOWS_RESERVED_NAMES:
        return False, f"'{name}' is a reserved system name and cannot be used"
    if '.' in name_upper and name_upper.split('.')[0] in WINDOWS_RESERVED_NAMES:
        return False, f"'{name}' uses a reserved system name and cannot be used"
    dangerous_chars = ['<', '>', ':', '"', '|', '?', '*', '\\', '/']
    if any(char in name for char in dangerous_chars):
        found = ', '.join(char for char in dangerous_chars if char in name)
        return False, f'Theme name contains invalid characters: {found}'
    if '..' in name or (name.startswith('.') and name != '.') or name.endswith('.'):
        return False, 'Theme name contains invalid path elements'
    return True, None
