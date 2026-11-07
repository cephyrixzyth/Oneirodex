"""Resource limits for administrator supplied image uploads."""

LIBRARY_IMAGE_MAX_BYTES = 10 * 1024 * 1024
LIBRARY_IMAGE_MAX_PIXELS = 16_000_000
LIBRARY_IMAGE_ALLOWED_FORMATS = frozenset({'GIF', 'JPEG', 'PNG', 'WEBP'})
GAME_IMAGE_MAX_BYTES = 3 * 1024 * 1024
GAME_IMAGE_MAX_PIXELS = 60_000_000
GAME_IMAGE_FORMAT_EXTENSIONS = {'GIF': 'gif', 'JPEG': 'jpg', 'PNG': 'png'}
LIBRARY_PREVIEW_MAX_BODY_BYTES = ((LIBRARY_IMAGE_MAX_BYTES + 2) // 3) * 4 + 128 * 1024
CUSTOM_EMOJI_MAX_PIXELS = 4_000_000


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
