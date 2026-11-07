from __future__ import annotations

import pytest

from oneirodex.utils.image_upload_limits import GAME_IMAGE_WORKER, ImageWorkBusy, prepare_game_image


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
