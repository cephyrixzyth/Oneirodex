"""Framework-independent health response payloads shared by native routes."""

from __future__ import annotations


def liveness_payload(version: str) -> dict[str, str]:
    """Return the stable process-liveness contract without touching Flask/DB."""
    return {
        'status': 'ok',
        'probe': 'liveness',
        'version': version,
    }
