from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

from flask import Flask
from PIL import Image
from werkzeug.datastructures import FileStorage

from oneirodex.routes_admin_ext import libraries


def test_legacy_library_upload_normalizes_supported_content_despite_suffix(tmp_path):
    app = Flask(__name__)
    app.secret_key = 'test-only'
    app.config['UPLOAD_FOLDER'] = str(tmp_path / 'uploads')
    image = Image.new('RGB', (2, 2), 'blue')
    source = BytesIO()
    image.save(source, format='PNG')
    upload = FileStorage(stream=BytesIO(source.getvalue()), filename='image.jpg')
    library = SimpleNamespace(image_url=None)

    with app.test_request_context('/'):
        result = libraries._process_library_image(upload, library)

    assert result is True
    assert library.image_url and library.image_url.endswith('.png')
    saved = list((tmp_path / 'uploads' / 'images').glob('*.png'))
    assert len(saved) == 1
    with Image.open(saved[0]) as normalized:
        assert normalized.format == 'PNG'


def test_legacy_library_upload_rejects_large_dimensions_before_conversion(
    tmp_path, monkeypatch,
):
    app = Flask(__name__)
    app.secret_key = 'test-only'
    app.config['UPLOAD_FOLDER'] = str(tmp_path / 'uploads')
    library = SimpleNamespace(image_url=None)

    class OversizedHeader:
        format = 'PNG'
        size = (5000, 5000)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def convert(self, *_args):
            raise AssertionError('oversized image must be rejected before conversion')

    monkeypatch.setattr(libraries.PILImage, 'open', lambda _file: OversizedHeader())
    upload = FileStorage(stream=BytesIO(b'x'), filename='image.png')

    with app.test_request_context('/'):
        result = libraries._process_library_image(upload, library)

    assert result is False
    assert not list((tmp_path / 'uploads' / 'images').glob('*'))
