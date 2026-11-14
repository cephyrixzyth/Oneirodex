from types import SimpleNamespace

from oneirodex.runtime_native.library_reads import LibraryReadData


def test_batch_edit_fields_omit_unused_image_projection(monkeypatch):
    library = SimpleNamespace(uuid='lib-1')
    full_fields = {'uuid': 'lib-1', 'name': 'Library One', 'image_url': '/static/default.jpg'}
    monkeypatch.setattr(
        LibraryReadData,
        'public_fields',
        staticmethod(lambda _library: dict(full_fields)),
    )

    assert LibraryReadData.batch_edit_fields(library) == {
        'uuid': 'lib-1', 'name': 'Library One',
    }
    assert LibraryReadData.public_fields(library)['image_url'] == '/static/default.jpg'


def test_batch_edit_cap_error_matches_legacy_contract():
    body, status = LibraryReadData.batch_edit_cap_error(100)

    assert status == 400
    assert body == {
        'ok': False,
        'success': False,
        'error': 'library_uuids cap is 100',
        'message': 'library_uuids cap is 100',
        'error_code': 'bad_request',
        'status': 'rejected',
        'cap': 100,
    }
