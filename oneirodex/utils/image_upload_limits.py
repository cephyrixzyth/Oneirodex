"""Resource limits for administrator supplied image uploads."""

import asyncio
from contextlib import contextmanager
from io import BytesIO
from threading import BoundedSemaphore

LIBRARY_IMAGE_MAX_BYTES = 10 * 1024 * 1024
LIBRARY_IMAGE_MAX_PIXELS = 16_000_000
LIBRARY_IMAGE_ALLOWED_FORMATS = frozenset({'GIF', 'JPEG', 'PNG', 'WEBP'})
GAME_IMAGE_MAX_BYTES = 3 * 1024 * 1024
GAME_IMAGE_MAX_PIXELS = 60_000_000
GAME_IMAGE_COVER_MAX_SIZE = (1200, 1600)
GAME_IMAGE_FORMAT_EXTENSIONS = {'GIF': 'gif', 'JPEG': 'jpg', 'PNG': 'png'}
IMAGE_DECODE_WORKER = BoundedSemaphore(1)
GAME_IMAGE_WORKER = IMAGE_DECODE_WORKER
LIBRARY_PREVIEW_MAX_BODY_BYTES = ((LIBRARY_IMAGE_MAX_BYTES + 2) // 3) * 4 + 128 * 1024
CUSTOM_EMOJI_MAX_PIXELS = 4_000_000


class ImageWorkBusy(RuntimeError):
    """Raised when the process image-work slot is already occupied."""


async def run_image_work_in_threadpool(func, *args, on_cancel=None, **kwargs):
    """Run bounded image work without letting cancellation orphan its worker.

    Cancelling Starlette's thread-pool await does not stop a synchronous worker.
    Wait for that worker to finish before propagating cancellation so its image
    cleanup and any request-scoped database use complete before the scope closes.
    """
    import anyio
    from starlette.concurrency import run_in_threadpool

    worker = asyncio.create_task(run_in_threadpool(func, *args, **kwargs))
    direct_cancel = False
    with anyio.CancelScope(shield=True):
        while True:
            try:
                result = await asyncio.shield(worker)
                break
            except asyncio.CancelledError:
                if worker.cancelled():
                    raise
                # Each direct Task.cancel() bypasses AnyIO's shield. Keep
                # waiting through repeated cancellation before closing scope.
                direct_cancel = True

    if direct_cancel:
        if on_cancel is not None:
            on_cancel(result)
        raise asyncio.CancelledError
    try:
        await anyio.lowlevel.checkpoint()
    except asyncio.CancelledError:
        if on_cancel is not None:
            on_cancel(result)
        raise
    return result


@contextmanager
def image_decode_work_slot():
    """Limit decoded-image work to one concurrent operation per process."""
    if not IMAGE_DECODE_WORKER.acquire(blocking=False):
        raise ImageWorkBusy('Image processing is busy. Try again shortly.')
    try:
        yield
    finally:
        IMAGE_DECODE_WORKER.release()


def prepare_game_image(content: bytes, image_type: str) -> tuple[bytes, str]:
    """Validate game art and resize covers under the single process work slot.

    Static non-cover artwork is header-validated and returned unchanged, avoiding
    an unnecessary full pixel buffer. A busy slot fails quickly so callers can
    keep their request/event loop available and return a retryable response.
    """
    if not IMAGE_DECODE_WORKER.acquire(blocking=False):
        raise ImageWorkBusy('Image processing is busy. Try again shortly.')
    image = None
    output = None
    try:
        from PIL import Image as PILImage

        try:
            with PILImage.open(BytesIO(content)) as opened:
                opened.verify()
            with PILImage.open(BytesIO(content)) as opened:
                error = game_image_header_error(opened)
                if error:
                    raise ValueError(error)
                image_format = str(opened.format).upper()
                extension = GAME_IMAGE_FORMAT_EXTENSIONS[image_format]
                if image_type != 'cover' or (
                    opened.width <= GAME_IMAGE_COVER_MAX_SIZE[0]
                    and opened.height <= GAME_IMAGE_COVER_MAX_SIZE[1]
                ):
                    return content, extension
                image = opened.copy()
                image.thumbnail(GAME_IMAGE_COVER_MAX_SIZE, PILImage.LANCZOS)
                output = BytesIO()
                image.save(output, format=image_format)
                result = output.getvalue()
                output.close()
                output = None
                return result, extension
        except ValueError:
            raise
        except Exception:
            raise ValueError('Invalid image data') from None
    finally:
        try:
            if image is not None:
                image.close()
            if output is not None:
                output.close()
        finally:
            IMAGE_DECODE_WORKER.release()


def library_image_header_error(image) -> str | None:
    """Validate decoder-reported format and dimensions before pixel conversion."""
    image_format = str(getattr(image, 'format', '') or '').upper()
    if image_format not in LIBRARY_IMAGE_ALLOWED_FORMATS:
        return 'Choose a supported library image format.'
    width, height = getattr(image, 'size', (0, 0))
    if width <= 0 or height <= 0 or width * height > LIBRARY_IMAGE_MAX_PIXELS:
        return 'Library image dimensions are too large.'
    return None


def normalize_library_image(content: bytes) -> bytes:
    """Decode a bounded library image and return normalized PNG bytes."""
    if len(content) > LIBRARY_IMAGE_MAX_BYTES:
        raise ValueError('Library image must be 10 MB or smaller.')

    from PIL import Image as PILImage

    with image_decode_work_slot():
        with PILImage.open(BytesIO(content)) as opened:
            error = library_image_header_error(opened)
            if error:
                raise ValueError(error)
            image = opened.convert('RGBA')
            output = BytesIO()
            try:
                if image.width > 1024 or image.height > 1024:
                    image.thumbnail((1024, 1024), PILImage.LANCZOS)
                image.save(output, format='PNG')
                return output.getvalue()
            finally:
                image.close()
                output.close()


def validate_library_image_header(content: bytes) -> None:
    """Check decoded type and dimensions without loading pixels, under the gate."""
    if len(content) > LIBRARY_IMAGE_MAX_BYTES:
        raise ValueError('Library image must be 10 MB or smaller.')

    from PIL import Image as PILImage

    with image_decode_work_slot():
        with PILImage.open(BytesIO(content)) as opened:
            error = library_image_header_error(opened)
            if error:
                raise ValueError(error)


def game_image_header_error(image) -> str | None:
    """Validate game artwork from the decoder header, independent of filename."""
    image_format = str(getattr(image, 'format', '') or '').upper()
    if image_format not in GAME_IMAGE_FORMAT_EXTENSIONS:
        return 'Upload a JPG, PNG, or GIF.'
    width, height = getattr(image, 'width', 0), getattr(image, 'height', 0)
    if width <= 0 or height <= 0 or width * height > GAME_IMAGE_MAX_PIXELS:
        return 'That image is too big. The limit is 60 megapixels.'
    return None
