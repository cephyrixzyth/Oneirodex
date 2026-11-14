from __future__ import annotations

import multiprocessing

from oneirodex.utils.rom_archive_lock import (
    release_rom_expansion_lock,
    try_acquire_rom_expansion_lock,
)


def _try_lock_in_child(cache_root: str, results) -> None:
    descriptor = try_acquire_rom_expansion_lock(cache_root)
    results.put(descriptor is not None)
    if descriptor is not None:
        release_rom_expansion_lock(descriptor)


def test_rom_expansion_lock_is_shared_between_processes(tmp_path):
    descriptor = try_acquire_rom_expansion_lock(tmp_path)
    assert descriptor is not None
    context = multiprocessing.get_context("spawn")
    results = context.Queue()
    process = context.Process(target=_try_lock_in_child, args=(str(tmp_path), results))
    try:
        process.start()
        process.join(timeout=10)
        assert not process.is_alive()
        assert process.exitcode == 0
        assert results.get(timeout=2) is False
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        release_rom_expansion_lock(descriptor)

    next_descriptor = try_acquire_rom_expansion_lock(tmp_path)
    assert next_descriptor is not None
    release_rom_expansion_lock(next_descriptor)
