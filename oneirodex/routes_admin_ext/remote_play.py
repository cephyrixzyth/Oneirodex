"""Admin remote play settings page (React shell)."""

from flask_login import login_required

from oneirodex.utils.auth import admin_required
from oneirodex.utils.admin_spa import render_admin_spa

from . import admin2_bp


@admin2_bp.route('/admin/remote_play', methods=['GET'])
@login_required
@admin_required
def remote_play_page():
    return render_admin_spa(title='Remote play · Oneirodex Admin')
