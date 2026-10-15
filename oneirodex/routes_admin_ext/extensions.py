from flask_login import login_required
from oneirodex.utils.auth import admin_required
from oneirodex.utils.admin_spa import render_admin_spa
from . import admin2_bp

@admin2_bp.route('/admin/extensions')
@login_required
@admin_required
def extensions():
    return render_admin_spa(title='File Extensions · Oneirodex Admin')
