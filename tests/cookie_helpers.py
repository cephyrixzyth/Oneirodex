"""Read Partitioned Set-Cookie attributes on supported test Python versions."""
from __future__ import annotations

from collections.abc import Iterable
from http.cookies import Morsel, SimpleCookie
import re


_PARTITIONED = re.compile(r';\s*Partitioned(?=\s*(?:;|$))', re.IGNORECASE)


def parse_set_cookies(values: Iterable[str]) -> dict[str, tuple[Morsel[str], bool]]:
    result = {}
    for value in values:
        partitioned = bool(_PARTITIONED.search(value))
        # Pre-3.14 SimpleCookie rejects the whole header for this newer flag.
        # Preserve the flag separately instead of discarding its assertion.
        jar = SimpleCookie()
        jar.load(_PARTITIONED.sub('', value))
        for name, morsel in jar.items():
            result[name] = (morsel, partitioned)
    return result
