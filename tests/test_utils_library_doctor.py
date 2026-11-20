"""Tests for library doctor dry-run helpers (no DB / no network)."""

from oneirodex.utils.library_doctor import iter_game_folders, dry_run_folder, doctor_dry_run, doctor_write_proposals


def test_iter_game_folders_flat(tmp_path):
    (tmp_path / 'Game A').mkdir()
    (tmp_path / 'Game B').mkdir()
    (tmp_path / 'readme.txt').write_text('x')
    folders = iter_game_folders(str(tmp_path))
    assert len(folders) == 2


def test_iter_game_folders_letter_buckets(tmp_path):
    a = tmp_path / '_a'
    a.mkdir()
    (a / 'Alpha Game').mkdir()
    (a / 'Another').mkdir()
    s = tmp_path / '_s'
    s.mkdir()
    (s / 'Sacred').mkdir()
    folders = iter_game_folders(str(tmp_path))
    assert len(folders) == 3
    assert any(p.endswith('Alpha Game') for p in folders)


def test_dry_run_folder_fitgirl(tmp_path):
    folder = tmp_path / "Assassin's Creed Shadows [FitGirl Repack]"
    folder.mkdir()
    row = dry_run_folder(str(folder), template='{title}')
    assert row['cleaned_name'] == "Assassin's Creed Shadows"
    assert row['suggested_rename'] == "Assassin's Creed Shadows"
    assert row['steam_app_id'] is None
    assert row['rename_plan']


def test_dry_run_folder_steam_id(tmp_path):
    folder = tmp_path / 'barony (Steam 335240)'
    folder.mkdir()
    row = dry_run_folder(str(folder))
    assert row['steam_app_id'] == 335240
    assert row['cleaned_name'].lower() == 'barony'


def test_dry_run_folder_bare_number_is_not_a_steam_id(tmp_path):
    folder = tmp_path / 'barony (89881)'
    folder.mkdir()
    row = dry_run_folder(str(folder))
    assert row['steam_app_id'] is None
    assert row['cleaned_name'].lower() == 'barony'


def test_doctor_dry_run_limit(tmp_path):
    for name in ['One', 'Two', 'Three']:
        (tmp_path / name).mkdir()
    rows = doctor_dry_run([str(tmp_path)], limit=2)
    assert len(rows) == 2


def test_doctor_write_proposals(tmp_path):
    folder = tmp_path / 'Game X'
    folder.mkdir()
    rows = [{'path': str(folder), 'raw_name': 'Game X'}]
    results = doctor_write_proposals(rows, candidates_by_path={str(folder): [{'id': 1, 'name': 'Game X'}]})
    assert results[0]['ok'] is True
    assert (folder / 'oneirodex.proposal.json').exists()


def test_doctor_apply_renames(tmp_path):
    from oneirodex.utils.library_doctor import doctor_apply_renames
    folder = tmp_path / 'Game [FitGirl Repack]'
    folder.mkdir()
    rows = [{'path': str(folder), 'cleaned_name': 'Game'}]
    results = doctor_apply_renames(rows, allowed_bases=[str(tmp_path)], template='{title}')
    assert results[0]['ok'] is True
    assert (tmp_path / 'Game').is_dir()
    assert not folder.exists()
