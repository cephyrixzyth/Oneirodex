"""RetroArch-style .cht cheat library for browser / companion emulation."""

from __future__ import annotations

import os
import re
from typing import Any

from flask import current_app
from werkzeug.utils import secure_filename
from oneirodex.utils.library_paths import library_dir

_SAFE_UUID = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.I,
)

#: A real RetroArch .cht is a few KB; 1 MB leaves room for the largest curated
#: sets while stopping an upload that is really a disk-filling attempt.
MAX_CHEAT_FILE_BYTES = 1024 * 1024
#: Per game. The folder is listed on every details-page load.
MAX_CHEAT_FILES_PER_GAME = 200


class CheatLimitError(ValueError):
    """A cheat file is over the size limit, or the game is at its file cap.

    A ``ValueError`` so existing handlers still treat it as a refusal; routes
    that know about it map ``code`` (an ``api_error`` code) to the right 4xx.
    """

    def __init__(self, message: str, *, code: str):
        super().__init__(message)
        self.code = code


# Capability-language dialects (form hint → code normalize into .cht). No Class A brands.
CHEAT_DIALECTS = frozenset({
    'raw',
    'game_genie',
    'action_replay',
    'gameshark',
})

_DIALECT_LABELS = {
    'raw': 'Raw',
    'game_genie': 'GG-style',
    'action_replay': 'AR-style',
    'gameshark': 'GS-style',
}


def cheats_root() -> str:
    root = current_app.config.get('EMULATOR_CHEATS_PATH')
    if root:
        return root
    return os.path.join(library_dir(), 'cheats')


def _game_dir(game_uuid: str) -> str:
    if not _SAFE_UUID.match(game_uuid or ''):
        raise ValueError('Invalid game UUID')
    path = os.path.join(cheats_root(), game_uuid)
    os.makedirs(path, exist_ok=True)
    return path


def _assert_under_game_dir(game_uuid: str, path: str) -> str:
    """Resolve path and ensure it stays under EMULATOR_CHEATS_PATH/{uuid}/."""
    folder = os.path.realpath(_game_dir(game_uuid))
    resolved = os.path.realpath(path)
    if resolved != folder and not resolved.startswith(folder + os.sep):
        raise ValueError('Invalid cheat path')
    return resolved


def _too_large() -> CheatLimitError:
    return CheatLimitError(
        f'Cheat file is too large (limit {MAX_CHEAT_FILE_BYTES // (1024 * 1024)} MB)',
        code='payload_too_large',
    )


def _ensure_room(folder: str, dest: str) -> None:
    """Refuse a *new* cheat file once the game holds MAX_CHEAT_FILES_PER_GAME.

    Replacing a file that already exists never counts against the cap.
    """
    if os.path.isfile(dest):
        return
    existing = sum(
        1
        for name in os.listdir(folder)
        if name.lower().endswith('.cht') and os.path.isfile(os.path.join(folder, name))
    )
    if existing >= MAX_CHEAT_FILES_PER_GAME:
        raise CheatLimitError(
            f'This game already has the maximum of {MAX_CHEAT_FILES_PER_GAME} cheat files; '
            'delete one before adding another',
            code='conflict',
        )


def _write_atomic(dest: str, data: bytes) -> None:
    tmp = f'{dest}.tmp-{os.getpid()}'
    try:
        with open(tmp, 'wb') as handle:
            handle.write(data)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def _cht_filename(name: str) -> str:
    raw = (name or '').strip()
    if not raw:
        raise ValueError('name required')
    safe = secure_filename(raw)
    if not safe:
        raise ValueError('name required')
    if not safe.lower().endswith('.cht'):
        safe = f'{safe}.cht'
    safe = secure_filename(safe)
    if not safe or not safe.lower().endswith('.cht'):
        raise ValueError('Only .cht files are supported')
    return safe


def _normalize_code(code: str, dialect: str | None) -> str:
    """Serialize operator code text into RetroArch cheatN_code form."""
    text = (code or '').strip()
    if not text:
        raise ValueError('code required')
    # Collapse whitespace; join multi-token lines with + (RetroArch convention).
    parts = re.split(r'\s+', text)
    if dialect in (None, 'raw') and len(parts) == 1:
        return parts[0]
    return '+'.join(parts)


def _normalize_dialect(dialect: Any) -> str | None:
    if dialect is None or dialect == '':
        return None
    value = str(dialect).strip().lower().replace('-', '_').replace(' ', '_')
    if value not in CHEAT_DIALECTS:
        raise ValueError(
            'dialect must be one of: raw, game_genie, action_replay, gameshark'
        )
    return value


def build_cht_text(
    *,
    name: str,
    codes: list[Any],
    dialect: str | None = None,
) -> str:
    """Build RetroArch .cht body from easy-create payload."""
    if not (name or '').strip():
        raise ValueError('name required')
    if not isinstance(codes, list) or not codes:
        raise ValueError('codes required')

    dialect = _normalize_dialect(dialect)
    label = _DIALECT_LABELS.get(dialect or '', '')
    lines = [f'cheats = {len(codes)}', '']

    for index, row in enumerate(codes):
        if not isinstance(row, dict):
            raise ValueError('each code must be an object with code')
        code_raw = row.get('code')
        if code_raw is None or str(code_raw).strip() == '':
            raise ValueError('code required')
        desc = (row.get('desc') or row.get('description') or '').strip()
        if not desc:
            desc = name.strip() if len(codes) == 1 else f'Code {index + 1}'
        if label and label.lower() not in desc.lower():
            desc = f'{label}: {desc}'
        code = _normalize_code(str(code_raw), dialect)
        # Escape quotes in desc for .cht string values
        desc_safe = desc.replace('\\', '\\\\').replace('"', '\\"')
        code_safe = code.replace('\\', '\\\\').replace('"', '\\"')
        lines.append(f'cheat{index}_desc = "{desc_safe}"')
        lines.append(f'cheat{index}_code = "{code_safe}"')
        lines.append(f'cheat{index}_enable = false')
        lines.append('')

    return '\n'.join(lines).rstrip() + '\n'


def list_cheat_files(game_uuid: str) -> list[dict[str, Any]]:
    folder = _game_dir(game_uuid)
    rows = []
    for name in sorted(os.listdir(folder)):
        if not name.lower().endswith('.cht'):
            continue
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        rows.append({
            'name': name,
            'size': os.path.getsize(path),
            'url': f'/api/games/{game_uuid}/cheats/{name}',
        })
    return rows


def read_cheat_file(game_uuid: str, filename: str) -> bytes:
    safe = secure_filename(filename)
    if not safe.lower().endswith('.cht'):
        raise ValueError('Only .cht files are supported')
    path = _assert_under_game_dir(game_uuid, os.path.join(_game_dir(game_uuid), safe))
    if not os.path.isfile(path):
        raise FileNotFoundError('Cheat file not found')
    with open(path, 'rb') as handle:
        return handle.read()


def store_cheat_file(game_uuid: str, file_storage) -> dict[str, Any]:
    safe = secure_filename(getattr(file_storage, 'filename', None) or '')
    if not safe.lower().endswith('.cht'):
        raise ValueError('Only .cht files are supported')
    folder = _game_dir(game_uuid)
    dest = _assert_under_game_dir(game_uuid, os.path.join(folder, safe))
    _ensure_room(folder, dest)
    # Read one byte past the limit instead of trusting Content-Length: the body
    # is never held (or written) beyond MAX_CHEAT_FILE_BYTES + 1.
    stream = getattr(file_storage, 'stream', file_storage)
    data = stream.read(MAX_CHEAT_FILE_BYTES + 1)
    if len(data) > MAX_CHEAT_FILE_BYTES:
        raise _too_large()
    _write_atomic(dest, data)
    return {
        'name': safe,
        'size': os.path.getsize(dest),
        'url': f'/api/games/{game_uuid}/cheats/{safe}',
    }


def create_cheat_file(
    game_uuid: str,
    *,
    name: str,
    codes: list[Any],
    dialect: str | None = None,
) -> dict[str, Any]:
    """Write a new .cht from easy-create JSON under EMULATOR_CHEATS_PATH/{uuid}/."""
    safe = _cht_filename(name)
    dialect = _normalize_dialect(dialect)
    body = build_cht_text(name=name, codes=codes, dialect=dialect)
    encoded = body.encode('utf-8')
    if len(encoded) > MAX_CHEAT_FILE_BYTES:
        raise _too_large()
    folder = _game_dir(game_uuid)
    dest = _assert_under_game_dir(game_uuid, os.path.join(folder, safe))
    _ensure_room(folder, dest)
    # ``build_cht_text`` joins with newline='\n' already; write the bytes as-is.
    _write_atomic(dest, encoded)
    row: dict[str, Any] = {
        'name': safe,
        'size': os.path.getsize(dest),
        'url': f'/api/games/{game_uuid}/cheats/{safe}',
        'created': True,
    }
    if dialect:
        row['dialect'] = dialect
    return row


def delete_cheat_file(game_uuid: str, filename: str) -> None:
    safe = secure_filename(filename)
    path = _assert_under_game_dir(game_uuid, os.path.join(_game_dir(game_uuid), safe))
    if os.path.isfile(path):
        os.remove(path)
