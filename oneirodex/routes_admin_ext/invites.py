from flask import request, flash, redirect, url_for, jsonify
from flask_login import login_required
from oneirodex.utils.auth import admin_required
from oneirodex.utils.admin_spa import render_admin_spa
from oneirodex.models import User, InviteToken
from oneirodex import db
from sqlalchemy import select, func, and_
import uuid
from . import admin2_bp
from oneirodex.schemas.invites import AdjustInviteQuotaBody
from oneirodex.utils.validation import validate_body
from oneirodex.utils.api_response import api_ok, api_error

@admin2_bp.route('/admin/api/invites', methods=['GET'])
@login_required
@admin_required
def list_invites_api():
    users = db.session.execute(select(User).order_by(User.name.asc())).scalars().all()
    user_invite_counts = db.session.execute(
        select(
            User.user_id,
            func.count(InviteToken.id).label('unused_count'),
        )
        .select_from(User)
        .outerjoin(
            InviteToken,
            and_(
                InviteToken.creator_user_id == User.user_id,
                InviteToken.used.is_(False),
            ),
        )
        .group_by(User.user_id)
    ).all()
    unused = {row.user_id: int(row.unused_count or 0) for row in user_invite_counts}
    return jsonify({
        'users': [
            {
                'id': u.id,
                'user_id': u.user_id,
                'name': u.name,
                'email': u.email,
                'role': u.role,
                'invite_quota': int(u.invite_quota or 0),
                'unused_invites': unused.get(u.user_id, 0),
            }
            for u in users
        ]
    })


@admin2_bp.route('/admin/api/invites/quota', methods=['POST'])
@login_required
@admin_required
@validate_body(AdjustInviteQuotaBody)
def adjust_invite_quota(body: AdjustInviteQuotaBody):
    user = db.session.execute(
        select(User).filter_by(user_id=str(body.user_id)).with_for_update()
    ).scalars().first()
    if user is None:
        return api_error('User not found.', code='not_found')
    user.invite_quota = int(user.invite_quota or 0) + body.invites_number
    db.session.commit()
    return api_ok(user_id=user.user_id, invite_quota=user.invite_quota)


@admin2_bp.route('/admin/invites', methods=['GET'])
@login_required
@admin_required
def invites_spa():
    return render_admin_spa(title='Invites · Oneirodex Admin')


@admin2_bp.route('/admin/manage_invites', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_invites():

    if request.method == 'POST':
        user_id = request.form.get('user_id')
        invites_number_str = request.form.get('invites_number')
        
        # Input validation for user_id
        if not user_id:
            flash('User ID is required.', 'error')
            return redirect(url_for('admin2.manage_invites'))
        
        # Validate UUID format
        try:
            uuid.UUID(user_id)
        except (ValueError, TypeError):
            flash('Invalid user ID format.', 'error')
            return redirect(url_for('admin2.manage_invites'))
        
        # Error handling for invites_number with proper validation
        try:
            invites_number = int(invites_number_str) if invites_number_str else 0
        except (ValueError, TypeError):
            flash('Invalid invite number provided. Please enter a valid number.', 'error')
            return redirect(url_for('admin2.manage_invites'))
        
        # Input validation for reasonable bounds
        if invites_number < -1000 or invites_number > 1000:
            flash('Invite number must be between -1000 and 1000.', 'error')
            return redirect(url_for('admin2.manage_invites'))

        # Better user lookup with proper error handling
        try:
            user = db.session.execute(select(User).filter_by(user_id=user_id)).scalars().first()
            if user:
                user.invite_quota += invites_number
                db.session.commit()
                flash(f'Invites updated successfully. User {user.name} now has {user.invite_quota} invite quota.', 'success')
            else:
                flash('User not found.', 'error')
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating invites: {str(e)}', 'error')
            return redirect(url_for('admin2.manage_invites'))

        return render_admin_spa(title='Invites · Oneirodex Admin')

    return render_admin_spa(title='Invites · Oneirodex Admin')
