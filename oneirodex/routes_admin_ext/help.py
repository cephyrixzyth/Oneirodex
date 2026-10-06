from flask import redirect, render_template
from flask_login import login_required

from oneirodex.utils.auth import admin_required
from . import admin2_bp


@admin2_bp.route('/admin/help')
@login_required
@admin_required
def admin_help():
    """Display the administrator help page"""
    # Keep admin and member Help on the same source of truth and presentation.
    return redirect('/help', code=302)


@admin2_bp.route('/admin/plugins')
@login_required
@admin_required
def admin_plugins():
    """React PluginsPage mounts when legacy body is empty."""
    return render_template('admin/admin_plugins.html')
