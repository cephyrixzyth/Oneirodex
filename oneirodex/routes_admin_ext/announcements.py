"""Admin announcements composer shell (React SPA page)."""

from flask_login import login_required

from oneirodex.utils.auth import admin_required
from oneirodex.utils.admin_spa import render_admin_spa

from . import admin2_bp


@admin2_bp.route('/admin/announcements', methods=['GET'])
@login_required
@admin_required
def announcements_page():
    """Shell for the React announcements composer."""
    return render_admin_spa(title='Announcements · Oneirodex Admin')
