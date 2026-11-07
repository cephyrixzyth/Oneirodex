"""Resource limits for administrator supplied image uploads."""

from io import BytesIO
from threading import BoundedSemaphore

LIBRARY_IMAGE_MAX_BYTES = 10 * 1024 * 1024
LIBRARY_IMAGE_MAX_PIXELS = 16_000_000
LIBRARY_IMAGE_ALLOWED_FORMATS = frozenset({'GIF', 'JPEG', 'PNG', 'WEBP'})
GAME_IMAGE_MAX_BYTES = 3 * 1024 * 1024
GAME_IMAGE_MAX_PIXELS = 60_000_000
GAME_IMAGE_COVER_MAX_SIZE = (1200, 1600)
GAME_IMAGE_FORMAT_EXTENSIONS = {'GIF': 'gif', 'JPEG': 'jpg', 'PNG': 'png'}
GAME_IMAGE_WORKER = BoundedSemaphore(1)
LIBRARY_PREVIEW_MAX_BODY_BYTES = ((LIBRARY_IMAGE_MAX_BYTES + 2) // 3) * 4 + 128 * 1024
CUSTOM_EMOJI_MAX_PIXELS = 4_000_000


class ImageWorkBusy(RuntimeError):
    """Raised when the process image-work slot is already occupied."""


def prepare_game_image(content: bytes, image_type: str) -> tuple[bytes, str]:
    """Validate game art and resize covers under the single process work slot.

    Static non-cover artwork is header-validated and returned unchanged, avoiding
    an unnecessary full pixel buffer. A busy slot fails quickly so callers can
    keep their request/event loop available and return a retryable response.
    """
    if not GAME_IMAGE_WORKER.acquire(blocking=False):
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
            GAME_IMAGE_WORKER.release()


def library_image_header_error(image) -> str | None:
    """Validate decoder-reported format and dimensions before pixel conversion."""
    image_format = str(getattr(image, 'format', '') or '').upper()
    if image_format not in LIBRARY_IMAGE_ALLOWED_FORMATS:
        return 'Choose a supported library image format.'
    width, height = getattr(image, 'size', (0, 0))
    if width <= 0 or height <= 0 or width * height > LIBRARY_IMAGE_MAX_PIXELS:
        return 'Library image dimensions are too large.'
    return None


def game_image_header_error(image) -> str | None:
    """Validate game artwork from the decoder header, independent of filename."""
    image_format = str(getattr(image, 'format', '') or '').upper()
    if image_format not in GAME_IMAGE_FORMAT_EXTENSIONS:
        return 'Upload a JPG, PNG, or GIF.'
    width, height = getattr(image, 'width', 0), getattr(image, 'height', 0)
    if width <= 0 or height <= 0 or width * height > GAME_IMAGE_MAX_PIXELS:
        return 'That image is too big. The limit is 60 megapixels.'
    return None
