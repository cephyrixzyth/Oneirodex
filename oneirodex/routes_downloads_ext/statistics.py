from flask import jsonify
from flask_login import login_required
from oneirodex.utils.statistics import get_download_statistics
from oneirodex.utils.auth import admin_required
from oneirodex.utils.admin_spa import render_admin_spa
from . import download_bp

@download_bp.route('/admin/statistics')
@login_required
@admin_required
def statistics():
    """Display the statistics page"""
    return render_admin_spa(title='Statistics · Oneirodex Admin')

@download_bp.route('/admin/statistics/data')
@login_required
@admin_required
def statistics_data():
    """Return JSON data for the statistics charts"""
    stats = get_download_statistics()
    return jsonify(stats)
