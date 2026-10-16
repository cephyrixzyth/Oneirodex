"""Table sorting ownership checks for the React admin shell."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADMIN = ROOT / 'frontend' / 'admin-app' / 'src'

def read(path):
    return path.read_text(encoding='utf-8')

def test_scan_jobs_use_shared_data_table():
    page = read(ADMIN / 'pages' / 'ScansPage.tsx')
    assert '<DataTable' in page
    assert "key: 'status'" in page
    assert "key: 'library'" in page
    assert "key: 'scan_folder'" in page

def test_unmatched_review_uses_shared_data_table():
    source = read(ADMIN / 'components' / 'DupeGlance.tsx')
    assert 'sortKey' in source
    assert 'aria-pressed={sortKey === key}' in source

def test_data_table_has_accessible_sort_controls():
    source = read(ROOT / 'frontend' / 'shared' / 'src' / 'DataTable.tsx')
    assert 'aria-sort' in source
    assert 'sort' in source.lower()
