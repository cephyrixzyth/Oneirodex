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


def test_native_threadpool_cancellation_keeps_gate_until_image_cleanup():
    """A cancelled native request cannot free its slot before worker cleanup."""
    from starlette.concurrency import run_in_threadpool

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
        task = asyncio.create_task(run_in_threadpool(gated_image_work))
        try:
            assert await asyncio.to_thread(worker_started.wait, 5)
            task.cancel()
            await asyncio.sleep(0)

            # Cancellation may return before a synchronous worker can stop, but
            # that worker must retain the shared slot until cleanup completes.
            assert task.done()
            assert not IMAGE_DECODE_WORKER.acquire(blocking=False)
        finally:
            allow_worker_cleanup.set()

        with pytest.raises(asyncio.CancelledError):
            await task
        assert await asyncio.to_thread(worker_cleaned.wait, 5)

    asyncio.run(scenario())
    assert IMAGE_DECODE_WORKER.acquire(blocking=False)
    IMAGE_DECODE_WORKER.release()
