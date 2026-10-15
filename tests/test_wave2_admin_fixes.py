"""Wave-2 regression guards for admin back-links and library edit scan_depth."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_no_admin2_admin_dashboard_url_for():
    admin_templates = ROOT / 'oneirodex' / 'templates' / 'admin'
    hits = []
    for path in admin_templates.rglob('*.html'):
        text = path.read_text(encoding='utf-8')
        if "admin2.admin_dashboard" in text:
            hits.append(str(path.relative_to(ROOT)))
    assert hits == [], f"Broken admin back-links remain: {hits}"


def test_edit_library_seeds_scan_depth_only_on_get():
    src = (ROOT / 'oneirodex' / 'routes_admin_ext' / 'libraries.py').read_text(encoding='utf-8')
    assert "if request.method == 'GET':" in src
    assert 'form.scan_depth.data = getattr(library, \'scan_depth\', 1) or 1' in src
    # Must not assign scan_depth from DB unconditionally before validate_on_submit
    before_validate, _, after = src.partition('def edit_library')
    edit_fn = after.split('def ', 1)[0] if 'def ' in after else after
    # Find the block between platform.choices and validate_on_submit
    chunk = edit_fn.split('form.validate_on_submit')[0]
    assert "if request.method == 'GET':" in chunk
    # Unconditional assignment lines should not appear outside the GET block as siblings
    # (simple guard: count of scan_depth.data assignments in edit_library == 1 inside GET)
    assert chunk.count('form.scan_depth.data') == 1


def test_member_and_admin_chrome_use_the_shared_feature_flag():
    member = (ROOT / 'oneirodex' / 'utils' / 'member_spa.py').read_text(encoding='utf-8')
    admin = (ROOT / 'oneirodex' / 'utils' / 'admin_spa.py').read_text(encoding='utf-8')
    assert 'enable-new-chrome' in member
    assert 'data-chrome="v2"' in admin
    assert 'ENABLE_NEW_CHROME' in member and 'ENABLE_NEW_CHROME' in admin
