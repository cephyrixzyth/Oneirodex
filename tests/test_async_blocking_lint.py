"""The blocking-call-in-async-handler ratchet detector.

``scripts/async_blocking_lint.py`` stops new ``async def`` native handlers
from querying the database on the event loop. These tests cover the detector,
not the current count. No database needed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import async_blocking_lint as lint  # noqa: E402


def _count(tmp_path: Path, source: str) -> int:
    target = tmp_path / "probe.py"
    target.write_text(source, encoding="utf-8")
    return lint.count_blocking_calls(target)


@pytest.mark.parametrize(
    "source",
    [
        "async def h(request):\n    auth = request_auth_context(request, {})\n",
        "async def h(request):\n    return data.read(user, 'g')\n",
        "def factory():\n    async def h(request):\n        if x:\n            data.write(1)\n    return h\n",
    ],
)
def test_direct_blocking_calls_in_async_handlers_are_counted(tmp_path, source):
    assert _count(tmp_path, source) == 1


@pytest.mark.parametrize(
    "source",
    [
        "def h(request):\n    return data.read(user, 'g')\n",
        "async def h(request):\n    return await run_in_threadpool(data.read, user, 'g')\n",
        "async def h(request):\n    return await run_in_threadpool(partial(request_auth_context, request))\n",
        "async def h(request):\n    def inner():\n        return data.read()\n    return await run_in_threadpool(inner)\n",
        "async def h(request):\n    return await run_in_threadpool(lambda: data.read())\n",
        "async def h(request):\n    return other.read()\n",
    ],
)
def test_threadpool_and_sync_handlers_are_not_counted(tmp_path, source):
    assert _count(tmp_path, source) == 0


def test_compare_flags_growth_and_reports_reductions():
    regressions, improvements = lint.compare({"a.py": 3, "b.py": 1, "new.py": 1}, {"a.py": 2, "b.py": 2})
    assert regressions == [("a.py", 2, 3), ("new.py", 0, 1)]
    assert improvements == [("b.py", 2, 1)]


def test_repository_is_within_its_baseline():
    regressions, _ = lint.compare(lint.scan(), lint.read_baseline())
    assert regressions == []
