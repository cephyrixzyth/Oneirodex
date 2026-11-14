from __future__ import annotations

import struct
import zlib
from io import BytesIO
from types import SimpleNamespace

from flask import Flask
from PIL import Image
import pytest
from werkzeug.datastructures import FileStorage

from oneirodex.utils import avatar


def _save_upload(image: Image.Image, filename: str) -> FileStorage:
    content = BytesIO()
    image.save(content, format=filename.rsplit(".", 1)[-1].upper())
    content.seek(0)
    return FileStorage(stream=content, filename=filename)


def _png_header(width: int, height: int) -> bytes:
    """Small PNG header whose dimensions can be checked without decoding pixels."""
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    def png_chunk(kind: bytes, data: bytes) -> bytes:
        chunk = kind + data
        return struct.pack(">I", len(data)) + chunk + struct.pack(">I", zlib.crc32(chunk))

    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", header)
        + png_chunk(b"IDAT", zlib.compress(b""))
        + png_chunk(b"IEND", b"")
    )


def test_avatar_upload_rejects_oversized_dimensions_before_decoding(tmp_path, monkeypatch):
    app = Flask(__name__)
    app.config["UPLOAD_FOLDER"] = str(tmp_path)
    user = SimpleNamespace(avatarpath="existing.png")
    upload = FileStorage(stream=BytesIO(_png_header(5000, 5000)), filename="huge.png")

    def fail_if_decoded(*_args, **_kwargs):
        raise AssertionError("oversized avatar pixels must be rejected before resize/decode")

    monkeypatch.setattr("oneirodex.utils.functions.square_image", fail_if_decoded)
    monkeypatch.setattr(Image.Image, "load", fail_if_decoded)
    path, error = avatar.save_avatar(upload, user, app)

    assert path is None
    assert error and "16-megapixel" in error
    assert user.avatarpath == "existing.png"
    assert list((tmp_path / "images" / "avatars_users").iterdir()) == []


def test_small_avatar_upload_still_saves_full_and_thumbnail(tmp_path):
    app = Flask(__name__)
    app.config["UPLOAD_FOLDER"] = str(tmp_path)
    user = SimpleNamespace(avatarpath=None)
    upload = _save_upload(Image.new("RGB", (80, 60), "green"), "member.png")

    path, error = avatar.save_avatar(upload, user, app)

    assert error is None
    assert path == user.avatarpath
    image_path = tmp_path / "images" / "avatars_users" / path.rsplit("/", 1)[-1]
    assert image_path.is_file()
    assert image_path.with_name(f"{image_path.stem}_thumbnail.png").is_file()


def test_avatar_format_comes_from_decoded_content_not_filename(tmp_path):
    app = Flask(__name__)
    app.config["UPLOAD_FOLDER"] = str(tmp_path)
    user = SimpleNamespace(avatarpath=None)
    content = BytesIO()
    Image.new("RGB", (80, 60), "green").save(content, format="PNG")
    content.seek(0)
    upload = FileStorage(stream=content, filename="member.jpg")

    path, error = avatar.save_avatar(upload, user, app)

    assert error is None
    assert path.endswith(".png")
    image_path = tmp_path / "images" / "avatars_users" / path.rsplit("/", 1)[-1]
    with Image.open(image_path) as saved:
        assert saved.format == "PNG"


def test_avatar_rejects_unsupported_decoded_format(tmp_path):
    app = Flask(__name__)
    app.config["UPLOAD_FOLDER"] = str(tmp_path)
    user = SimpleNamespace(avatarpath="existing.png")
    content = BytesIO()
    Image.new("RGB", (20, 20), "purple").save(content, format="TIFF")
    content.seek(0)
    upload = FileStorage(stream=content, filename="member.png")

    path, error = avatar.save_avatar(upload, user, app)

    assert path is None
    assert error and "supported avatar image format" in error
    assert user.avatarpath == "existing.png"
    assert list((tmp_path / "images" / "avatars_users").iterdir()) == []


def test_avatar_work_gate_rejects_overlap_without_leaving_staged_files(tmp_path):
    app = Flask(__name__)
    app.config["UPLOAD_FOLDER"] = str(tmp_path)
    user = SimpleNamespace(avatarpath="existing.png")
    upload = _save_upload(Image.new("RGB", (20, 20), "green"), "member.png")

    from oneirodex.utils.image_upload_limits import IMAGE_DECODE_WORKER

    assert IMAGE_DECODE_WORKER.acquire(blocking=False)
    try:
        path, error = avatar.save_avatar(upload, user, app)
    finally:
        IMAGE_DECODE_WORKER.release()

    assert path is None
    assert error and "busy" in error
    assert user.avatarpath == "existing.png"
    assert list((tmp_path / "images" / "avatars_users").iterdir()) == []


def test_animated_avatar_within_limits_keeps_its_frames(tmp_path):
    app = Flask(__name__)
    app.config["UPLOAD_FOLDER"] = str(tmp_path)
    user = SimpleNamespace(avatarpath=None)
    first = Image.new("RGB", (40, 40), "red")
    second = Image.new("RGB", (40, 40), "blue")
    content = BytesIO()
    first.save(content, format="GIF", save_all=True, append_images=[second], duration=50, loop=0)
    content.seek(0)
    upload = FileStorage(stream=content, filename="animated.gif")

    path, error = avatar.save_avatar(upload, user, app)

    assert error is None
    image_path = tmp_path / "images" / "avatars_users" / path.rsplit("/", 1)[-1]
    with Image.open(image_path) as saved:
        assert saved.n_frames == 2


def test_animated_avatar_over_frame_limit_keeps_previous_avatar_and_cleans_files(tmp_path, monkeypatch):
    app = Flask(__name__)
    app.config["UPLOAD_FOLDER"] = str(tmp_path)
    upload_folder = tmp_path / "images" / "avatars_users"
    upload_folder.mkdir(parents=True)
    old_avatar = upload_folder / "existing.png"
    old_avatar.write_bytes(b"existing avatar remains")
    user = SimpleNamespace(avatarpath=f"{avatar.AVATAR_URL_PREFIX}existing.png")
    first = Image.new("RGB", (40, 40), "red")
    second = Image.new("RGB", (40, 40), "blue")
    third = Image.new("RGB", (40, 40), "green")
    content = BytesIO()
    first.save(
        content,
        format="GIF",
        save_all=True,
        append_images=[second, third],
        duration=50,
        loop=0,
    )
    content.seek(0)
    upload = FileStorage(stream=content, filename="too-many-frames.gif")
    monkeypatch.setattr(avatar, "MAX_AVATAR_FRAMES", 2)

    path, error = avatar.save_avatar(upload, user, app)

    assert path is None
    assert error and "2-frame limit" in error
    assert user.avatarpath == f"{avatar.AVATAR_URL_PREFIX}existing.png"
    assert old_avatar.read_bytes() == b"existing avatar remains"
    assert set(upload_folder.iterdir()) == {old_avatar}


def test_avatar_file_cleanup_follows_database_commit_outcome(tmp_path):
    app = Flask(__name__)
    app.config["UPLOAD_FOLDER"] = str(tmp_path)
    upload_folder = tmp_path / "images" / "avatars_users"
    upload_folder.mkdir(parents=True)
    old_path = f"{avatar.AVATAR_URL_PREFIX}old.png"
    new_path = f"{avatar.AVATAR_URL_PREFIX}new.png"
    old_image = upload_folder / "old.png"
    old_thumbnail = upload_folder / "old_thumbnail.png"
    new_image = upload_folder / "new.png"
    new_thumbnail = upload_folder / "new_thumbnail.png"
    for path in (old_image, old_thumbnail, new_image, new_thumbnail):
        path.write_bytes(path.name.encode())

    avatar.finalize_avatar_change(app, old_path, new_path, committed=False)

    assert old_image.exists() and old_thumbnail.exists()
    assert not new_image.exists() and not new_thumbnail.exists()

    new_image.write_bytes(b"new image")
    new_thumbnail.write_bytes(b"new thumbnail")
    avatar.finalize_avatar_change(app, old_path, new_path, committed=True)

    assert not old_image.exists() and not old_thumbnail.exists()
    assert new_image.exists() and new_thumbnail.exists()


class _FakeFrame:
    def __init__(self, copies):
        self.copies = copies

    def copy(self):
        self.copies.append("thumbnail")
        return self

    def thumbnail(self, *_args, **_kwargs):
        return None

    def save(self, *_args, **_kwargs):
        return None


class _FakeGif:
    info = {"duration": 10}

    def __init__(self, frame_count: int, size=(8, 8)):
        self.frame_count = frame_count
        self.size = size
        self.frame = 0
        self.copies = []

    def tell(self):
        return self.frame

    def seek(self, frame):
        if frame >= self.frame_count:
            raise EOFError
        self.frame = frame

    def copy(self):
        self.copies.append(self.frame)
        return _FakeFrame(self.copies)


def test_animated_avatar_caps_frame_count_before_copying_more_frames(tmp_path, monkeypatch):
    monkeypatch.setattr(avatar, "MAX_AVATAR_FRAMES", 2)
    monkeypatch.setattr(avatar, "MAX_AVATAR_TOTAL_PIXELS", 10_000)
    image = _FakeGif(frame_count=3)

    with pytest.raises(avatar.AvatarResourceLimitError, match="2-frame limit"):
        avatar._resize_animated_gif(image, str(tmp_path / "avatar.gif"))

    assert image.copies == [0, 1]


def test_animated_avatar_caps_total_frame_pixels_before_copying_next_frame(tmp_path, monkeypatch):
    monkeypatch.setattr(avatar, "MAX_AVATAR_FRAMES", 200)
    monkeypatch.setattr(avatar, "MAX_AVATAR_TOTAL_PIXELS", 1_000_000)
    image = _FakeGif(frame_count=3, size=(800, 800))

    with pytest.raises(avatar.AvatarResourceLimitError, match="1-megapixel total frame limit"):
        avatar._resize_animated_gif(image, str(tmp_path / "avatar.gif"))

    assert image.copies == [0]
