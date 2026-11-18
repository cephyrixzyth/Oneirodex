"""Offline ROM dump→MT→rebuild pipeline stubs (no real rewrite yet)."""

from __future__ import annotations

from typing import Any


class BaseOfflineStub:
    """Default stub — documents that offline rebuild is not implemented."""

    id = 'generic_stub'
    platform = '*'
    status = 'unsupported'
    docs_url = '/docs/user/translation-patches.md'

    def supports(self, platform: str | None) -> bool:
        return False

    def extract(self, rom_path: str) -> dict[str, Any]:
        raise NotImplementedError(
            'Offline extract is not implemented. Use RetroArch AI Service overlay '
            'or a curated translation patch. See docs/user/translation-patches.md'
        )

    def translate(self, extracted: dict[str, Any], *, target_lang: str) -> dict[str, Any]:
        raise NotImplementedError(
            'Offline machine translate is not implemented in Oneirodex. '
            'Use an external dump/translate tool, then place a .bps/.ips under extras.'
        )

    def build(self, rom_path: str, translated: dict[str, Any], *, output_path: str) -> str:
        raise NotImplementedError(
            'Offline ROM rebuild is not implemented. Oneirodex will not mutate library ROMs.'
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'platform': self.platform,
            'status': self.status,
            'docs_url': self.docs_url,
            'supports_offline': False,
        }


class GbaOfflineStub(BaseOfflineStub):
    """GBA placeholder — points operators at external tools; not wired to mutate ROMs."""

    id = 'gba_stub'
    platform = 'GBA'
    status = 'stub'
    docs_url = '/docs/user/translation-patches.md'
