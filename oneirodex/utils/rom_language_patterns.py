"""Shared region and language filename patterns, independent of archive I/O."""
from __future__ import annotations

import re


LANG_LIST_PAREN_RE = re.compile(
    r'\s*\(((?:En|Fr|De|Es|It|Nl|Pt|Ru|Ja|Zh|Ko|Pl|Sv|No|Da|Fi|Hu|Cs|Tr|Ar)'
    r'(?:\s*,\s*(?:En|Fr|De|Es|It|Nl|Pt|Ru|Ja|Zh|Ko|Pl|Sv|No|Da|Fi|Hu|Cs|Tr|Ar))*)\)',
    re.IGNORECASE,
)
REGION_CAPTURE_RE = re.compile(
    r'\((USA|Europe|Japan|World|UE|JU|EU|JP|U|J|E|Asia|Brazil|Korea|'
    r'Australia|France|Germany|Spain|Italy|Netherlands|Sweden|China|'
    r'Hong Kong|Taiwan|Russia)(?:[^)]*)\)',
    re.IGNORECASE,
)
