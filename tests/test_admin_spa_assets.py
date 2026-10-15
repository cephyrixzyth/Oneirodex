"""Admin SPA asset wiring."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_admin_spa_dist_built():
    dist = ROOT / 'oneirodex' / 'static' / 'dist' / 'admin-app'
    assert (dist / 'admin-app.js').is_file()
    assert (dist / 'admin-app.css').is_file()


def test_entrypoint_warns_on_missing_admin_app():
    sh = (ROOT / 'entrypoint.sh').read_text(encoding='utf-8')
    assert 'admin-app.js' in sh
    assert 'admin-app.css' in sh


def test_dockerfile_builds_admin_app():
    text = (ROOT / 'Dockerfile').read_text(encoding='utf-8')
    assert 'frontend/admin-app' in text
    assert 'dist/admin-app' in text


def test_dockerfile_stages_tsconfig_base():
    """SPA `tsc --noEmit` extends repo-root tsconfig.base.json (Unraid image build)."""
    text = (ROOT / 'Dockerfile').read_text(encoding='utf-8')
    assert 'COPY tsconfig.base.json' in text


def test_admin_pilot_bundle_is_required_at_container_start():
    dockerfile = (ROOT / 'Dockerfile').read_text(encoding='utf-8')
    entrypoint = (ROOT / 'entrypoint.sh').read_text(encoding='utf-8')
    assert 'npm run build:pilot --workspace=admin-app' in dockerfile
    assert 'dist/admin-pilot /app/oneirodex/static/dist/admin-pilot' in dockerfile
    assert '/app/oneirodex/static/dist/admin-pilot/index.html' in entrypoint
    assert 'FastAPI admin page routes require the packaged admin-pilot/index.html bundle' in entrypoint
