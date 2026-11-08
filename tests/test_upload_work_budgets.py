from __future__ import annotations

import asyncio
from io import BytesIO
from threading import Event

from PIL import Image
import pytest

from oneirodex.utils import cover_art_studio
from oneirodex.utils.image_upload_limits import (
    GAME_IMAGE_WORKER,
    IMAGE_DECODE_WORKER,
    ImageWorkBusy,
    image_decode_work_slot,
    normalize_library_image,
    prepare_game_image,
    run_image_work_in_threadpool,
)


def test_game_image_work_slot_rejects_overlapping_decode_before_pillow():
    assert GAME_IMAGE_WORKER.acquire(blocking=False)
    try:
        with pytest.raises(ImageWorkBusy, match='busy'):
            prepare_game_image(b'not decoded while busy', 'cover')
    finally:
        GAME_IMAGE_WORKER.release()


def test_game_image_work_slot_releases_after_invalid_image():
    with pytest.raises(ValueError, match='Invalid image data'):
        prepare_game_image(b'not an image', 'cover')

    assert GAME_IMAGE_WORKER.acquire(blocking=False)
    GAME_IMAGE_WORKER.release()


def test_library_image_normalization_uses_the_shared_work_slot():
    content = BytesIO()
    Image.new('RGB', (24, 24), 'green').save(content, format='PNG')

    assert IMAGE_DECODE_WORKER.acquire(blocking=False)
    try:
        with pytest.raises(ImageWorkBusy, match='busy'):
            normalize_library_image(content.getvalue())
    finally:
        IMAGE_DECODE_WORKER.release()


def test_art_pack_fallback_image_loads_use_the_shared_work_slot(tmp_path, monkeypatch):
    pack_root = tmp_path / 'packs'
    pack_dir = pack_root / 'pack01'
    fallback_root = tmp_path / 'newstyle'
    pack_dir.mkdir(parents=True)
    (pack_dir / 'manifest.json').write_text('{"format":"png"}', encoding='utf-8')
    Image.new('RGB', (20, 20), 'green').save(pack_dir / 'tile_600x900.png')
    Image.new('RGB', (20, 20), 'blue').save(pack_dir / 'wide_1920x1080.png')
    monkeypatch.setattr(cover_art_studio, 'generated_root', lambda _root=None: pack_root)
    monkeypatch.setattr(cover_art_studio, 'newstyle_root', lambda _root=None: fallback_root)

    assert IMAGE_DECODE_WORKER.acquire(blocking=False)
    try:
        with pytest.raises(ImageWorkBusy, match='busy'):
            cover_art_studio.apply_pack_as_fallback('pack01', package_root=tmp_path)
    finally:
        IMAGE_DECODE_WORKER.release()

    assert list(fallback_root.iterdir()) == []


def test_art_pack_fallback_decodes_and_closes_generated_inputs(tmp_path, monkeypatch):
    pack_root = tmp_path / 'packs'
    pack_dir = pack_root / 'pack02'
    fallback_root = tmp_path / 'newstyle'
    pack_dir.mkdir(parents=True)
    (pack_dir / 'manifest.json').write_text('{"format":"png"}', encoding='utf-8')
    Image.new('RGB', (30, 40), 'green').save(pack_dir / 'tile_600x900.png')
    Image.new('RGB', (40, 30), 'blue').save(pack_dir / 'wide_1920x1080.png')
    monkeypatch.setattr(cover_art_studio, 'generated_root', lambda _root=None: pack_root)
    monkeypatch.setattr(cover_art_studio, 'newstyle_root', lambda _root=None: fallback_root)

    result = cover_art_studio.apply_pack_as_fallback('pack02', package_root=tmp_path)

    assert set(result) == {'default_cover', 'default_library', 'pack_id'}
    with Image.open(result['default_cover']) as cover:
        assert cover.format == 'JPEG'
    with Image.open(result['default_library']) as library:
        assert library.format == 'JPEG'
    assert IMAGE_DECODE_WORKER.acquire(blocking=False)
    IMAGE_DECODE_WORKER.release()


def test_image_threadpool_cancellation_waits_for_worker_cleanup():
    """The image worker helper defers request cancellation until cleanup."""
    worker_started = Event()
    allow_worker_cleanup = Event()
    worker_cleaned = Event()

    def gated_image_work():
        try:
            with image_decode_work_slot():
                worker_started.set()
                assert allow_worker_cleanup.wait(timeout=5)
        finally:
            worker_cleaned.set()

    async def scenario():
        task = asyncio.create_task(run_image_work_in_threadpool(gated_image_work))
        try:
            assert await asyncio.to_thread(worker_started.wait, 5)
            task.cancel()
            await asyncio.sleep(0)

            assert not task.done()
            assert not IMAGE_DECODE_WORKER.acquire(blocking=False)
        finally:
            allow_worker_cleanup.set()

        with pytest.raises(asyncio.CancelledError):
            await task
        assert await asyncio.to_thread(worker_cleaned.wait, 5)

    asyncio.run(scenario())
    assert IMAGE_DECODE_WORKER.acquire(blocking=False)
    IMAGE_DECODE_WORKER.release()


def test_anyio_cancellation_is_deferred_until_image_worker_finishes():
    import anyio

    worker_started = Event()
    allow_worker_cleanup = Event()
    cancellation_received = None
    cancellation_cleanup = []

    def gated_image_work():
        with image_decode_work_slot():
            worker_started.set()
            assert allow_worker_cleanup.wait(timeout=5)
            return 'image-result'

    async def scenario():
        nonlocal cancellation_received
        scope_ready = anyio.Event()
        cancellation_done = anyio.Event()
        cancel_scope_holder = {}

        async def request_work():
            nonlocal cancellation_received
            with anyio.CancelScope() as cancel_scope:
                cancel_scope_holder['scope'] = cancel_scope
                scope_ready.set()
                try:
                    await run_image_work_in_threadpool(
                        gated_image_work,
                        on_cancel=lambda result: cancellation_cleanup.append(result),
                    )
                except asyncio.CancelledError:
                    cancellation_received = True
                finally:
                    cancellation_done.set()

        async with anyio.create_task_group() as group:
            group.start_soon(request_work)
            await scope_ready.wait()
            assert await anyio.to_thread.run_sync(worker_started.wait, 5)
            cancel_scope_holder['scope'].cancel()
            await anyio.sleep(0.01)
            assert not cancellation_done.is_set()
            assert not IMAGE_DECODE_WORKER.acquire(blocking=False)
            assert cancellation_cleanup == []
            allow_worker_cleanup.set()
            await cancellation_done.wait()

    anyio.run(scenario)
    assert cancellation_received is True
    assert cancellation_cleanup == ['image-result']
    assert IMAGE_DECODE_WORKER.acquire(blocking=False)
    IMAGE_DECODE_WORKER.release()
