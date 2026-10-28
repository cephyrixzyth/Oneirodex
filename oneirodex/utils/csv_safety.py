"""Helpers for exporting untrusted text to spreadsheet-readable CSV."""

from __future__ import annotations


_FORMULA_PREFIXES = ('=', '+', '-', '@')


def neutralize_spreadsheet_formulas(row: dict) -> dict:
    """Prefix formula-like string cells so spreadsheet apps treat them as text.

    CSV quoting protects delimiters, not spreadsheet formula evaluation. Folder
    names and other exported text may come from filesystems or provider data.
    """
    safe = {}
    for key, value in row.items():
        if isinstance(value, str) and value.lstrip(' \t\r\n\v\f').startswith(_FORMULA_PREFIXES):
            safe[key] = "'" + value
        else:
            safe[key] = value
    return safe
