from oneirodex.utils.image_paths import image_path_under_save_dir


def test_image_path_accepts_bare_and_legacy_static_urls(tmp_path):
    root = tmp_path / 'images'

    assert image_path_under_save_dir('cover.jpg', root) == root / 'cover.jpg'
    assert (
        image_path_under_save_dir('/static/library/images/cover.jpg', root)
        == root / 'cover.jpg'
    )


def test_image_path_rejects_posix_and_windows_traversal(tmp_path):
    root = tmp_path / 'images'

    assert image_path_under_save_dir('../../outside.txt', root) is None
    assert image_path_under_save_dir(r'..\..\outside.txt', root) is None
    assert image_path_under_save_dir(r'C:\outside\secret.txt', root) is None


def test_image_path_rejects_symlink_resolving_outside_save_dir(tmp_path):
    root = tmp_path / 'images'
    root.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    link = root / 'link'
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (NotImplementedError, OSError):
        import pytest

        pytest.skip('directory symlinks are unavailable on this host')

    assert image_path_under_save_dir('link/secret.txt', root) is None


def test_image_path_keeps_final_symlink_lexical(tmp_path):
    root = tmp_path / 'images'
    root.mkdir()
    target = root / 'target.jpg'
    target.write_bytes(b'target')
    link = root / 'link.jpg'
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError):
        import pytest

        pytest.skip('file symlinks are unavailable on this host')

    assert image_path_under_save_dir('link.jpg', root) == link


def test_delete_game_images_removes_local_file_but_preserves_traversal_target(
    tmp_path,
):
    from oneirodex.runtime_native.db_session import _native_session
    from oneirodex.utils.scanning import delete_game_images

    root = tmp_path / 'images'
    root.mkdir()
    local_file = root / 'cover.jpg'
    local_file.write_bytes(b'local image')
    outside_file = tmp_path / 'outside.txt'
    outside_file.write_bytes(b'keep')
    image_rows = [
        type('ImageRow', (), {'url': 'cover.jpg'})(),
        type('ImageRow', (), {'url': '../outside.txt'})(),
    ]

    class FakeResult:
        def scalar_one_or_none(self):
            return object()

        def scalars(self):
            return self

        def all(self):
            return image_rows

    class FakeSession:
        def __init__(self):
            self.execute_count = 0
            self.deleted = []
            self.committed = False

        def execute(self, _statement):
            self.execute_count += 1
            return FakeResult()

        def delete(self, row):
            self.deleted.append(row)

        def commit(self):
            self.committed = True

        def rollback(self):
            raise AssertionError('unexpected rollback')

    session = FakeSession()
    token = _native_session.set(session)
    try:
        delete_game_images('game-uuid', config={'IMAGE_SAVE_PATH': str(root)})
    finally:
        _native_session.reset(token)

    assert not local_file.exists()
    assert outside_file.read_bytes() == b'keep'
    assert session.deleted == image_rows
    assert session.committed
