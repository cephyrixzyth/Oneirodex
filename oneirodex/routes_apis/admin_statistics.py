from flask_login import login_required

from oneirodex.utils.api_response import api_ok
from oneirodex.utils.auth import admin_required
from oneirodex.utils.statistics import get_download_statistics
from . import apis_bp


@apis_bp.route('/admin/statistics', methods=['GET'])
@login_required
@admin_required
def api_admin_statistics():
    """Return the existing admin statistics aggregates in the shared envelope."""
    return api_ok(get_download_statistics())
