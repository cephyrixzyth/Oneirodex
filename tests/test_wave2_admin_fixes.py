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


