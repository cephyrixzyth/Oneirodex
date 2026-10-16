"""The Python-built SPA shells load the shared aurora toast (UX-B7).

jQuery $.notify stayed on login/settings/admin after the SPAs moved to
od-toast. The bridge file replaces it so classic pages get the same
dismissible host without editing every theme script.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOAST_JS = ROOT / 'oneirodex' / 'static' / 'js' / 'od_toast.js'


def test_gt_toast_is_dismissible_and_bridges_notify():
    src = TOAST_JS.read_text(encoding='utf-8')
    assert 'od-toast__close' in src
    assert 'textContent' in src
    assert 'jq.notify =' in src
    assert 'innerHTML' not in src
    assert 'MAX_INDIVIDUAL_TOASTS = 5' in src
    assert 'notification' in src


def test_member_and_admin_shells_load_gt_toast_after_notify():
    needle = "js/od_toast.js"
    notify = 'vendor/notify/0.4.2/notify.min.js'
    for folder, name in (('utils', 'member_spa.py'), ('runtime_native', 'admin_pilot.py')):
        text = (ROOT / 'oneirodex' / folder / name).read_text(encoding='utf-8')
        assert needle in text, name
        assert notify in text, name
        assert text.index(notify) < text.index(needle), name
