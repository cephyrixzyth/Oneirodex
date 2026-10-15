"""Admin store-connection diagnostics page (LIB-04). The data comes from
``GET /api/admin/ownership/connections``; this only mounts the admin SPA."""

from flask_login import login_required

from oneirodex.utils.auth import admin_required
from oneirodex.utils.admin_spa import render_admin_spa

from . import admin2_bp


@admin2_bp.route('/admin/ownership', methods=['GET'])
@login_required
@admin_required
def ownership_diagnostics_spa():
    return render_admin_spa(title='Store connections · Oneirodex Admin')
