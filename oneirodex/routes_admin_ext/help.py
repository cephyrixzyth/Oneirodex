from flask_login import login_required

from oneirodex.utils.auth import admin_required
from oneirodex.utils.admin_spa import render_admin_spa
from . import admin2_bp


@admin2_bp.route('/admin/help')
@login_required
@admin_required
def admin_help():
    """Display the administrator help page"""
    # The admin shell supplies the dedicated React help page. Keep this fallback
    # for deployments that have not enabled the native static-shell route.
    return render_admin_spa(title='Admin help · Oneirodex Admin')


@admin2_bp.route('/admin/plugins')
@login_required
@admin_required
def admin_plugins():
    """React PluginsPage mounts when legacy body is empty."""
    return render_admin_spa(title='Export to emulator frontends · Oneirodex Admin')
