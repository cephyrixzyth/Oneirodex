"""The offline matcher triage script buckets cleaned names by leftover residue."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    'match_triage', Path(__file__).resolve().parents[1] / 'scripts' / 'match_triage.py'
)
triage_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(triage_mod)


def test_a_clean_label_has_no_residue():
    row = triage_mod.triage('Hades [FitGirl Repack]', [])
    assert row['cleaned'] == 'Hades' and row['residue'] == ['clean']


def test_leftover_tags_are_bucketed():
    row = triage_mod.triage('Cult of the Lamb (v1.4.7 + 3 DLCs)', [])
    assert 'dlc_or_bonus' in row['residue'] and 'bracket_or_paren_left' in row['residue']


def test_release_groups_passed_on_the_command_line_are_stripped():
    plain = triage_mod.triage('Baldurs.Gate.3-ElAmigos', [])
    stripped = triage_mod.triage('Baldurs.Gate.3-ElAmigos', ['ElAmigos'])
    assert 'ElAmigos'.lower() not in stripped['cleaned'].lower()
    assert 'group_tail' in plain['residue'] or 'elamigos' in plain['cleaned'].lower()


def test_csv_input_reads_the_folder_column(tmp_path):
    path = tmp_path / 'u.csv'
    path.write_text('folder_path,score\n/games/Portal 2,0.5\n/games/Hades,0.4\n')
    assert triage_mod._load_names(path) == ['Portal 2', 'Hades']
