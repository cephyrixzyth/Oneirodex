# /oneirodex/routes_admin_ext/users.py
from oneirodex.utils.api_response import api_error, api_ok
from flask import render_template, request, jsonify
from flask_login import login_required, current_user, login_user
from oneirodex.models import Library, User, Genre, Theme
from oneirodex import db
from sqlalchemy import select, func
from . import admin2_bp
from uuid import uuid4
from oneirodex.utils.event_logging import log_system_event
from oneirodex.utils.accounts import display_email, is_placeholder_email, placeholder_email
from oneirodex.utils.auth import admin_required
from oneirodex.utils.rbac import VALID_ROLES as RBAC_VALID_ROLES
from oneirodex.utils.library_acl import (
    get_user_content_filters,
    get_user_library_allowlist,
    set_user_content_filters,
    set_user_library_allowlist,
)
import re
from sqlalchemy.exc import IntegrityError

# Validation constants and functions
VALID_ROLES = list(RBAC_VALID_ROLES)
RESERVED_USERNAMES = ['system']

def validate_username(username):
    """Validate username according to business rules"""
    if not username or not isinstance(username, str):
        return False, "Username is required"
    
    if username.lower() in RESERVED_USERNAMES:
        return False, f"'{username}' is a reserved username and cannot be used"
    
    if not re.match(r'^[\w.]+$', username):
        return False, "Username can only contain letters, numbers, dots and underscores"
    
    if len(username) < 3 or len(username) > 64:
        return False, "Username must be between 3 and 64 characters long"
    
    return True, ""

def validate_email(email):
    """Validate email format and requirements"""
    if not email or not isinstance(email, str):
        return False, "Email is required"
    
    # Basic email regex validation
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, email):
        return False, "Invalid email format"
    
    if len(email) > 120:
        return False, "Email address too long"
    
    return True, ""

def validate_role(role):
    """Validate role is allowed"""
    if not role or not isinstance(role, str):
        return False, "Role is required"
    
    if role not in VALID_ROLES:
        return False, f"Role must be one of: {', '.join(VALID_ROLES)}"
    
    return True, ""

def validate_about(about):
    """Validate about field constraints"""
    if about is not None:
        if not isinstance(about, str):
            return False, "About field must be a string"
        if len(about) > 256:
            return False, "About field cannot exceed 256 characters"
    
    return True, ""

def check_email_unique(email, exclude_user_id=None):
    """Check if email is unique in the system"""
    query = db.session.execute(
        select(User).where(func.lower(User.email) == email.lower())
    ).scalars()
    
    existing_user = query.first()
    if existing_user and existing_user.id != exclude_user_id:
        return False, "Email address is already in use"
    return True, ""

def check_username_unique(username, exclude_user_id=None):
    """Check if username is unique in the system"""
    query = db.session.execute(
        select(User).where(func.lower(User.name) == username.lower())
    ).scalars()
    
    existing_user = query.first()
    if existing_user and existing_user.id != exclude_user_id:
        return False, "Username is already taken"
    return True, ""

def check_admin_protection(user_id, new_role=None, new_state=None):
    """Check if operation would leave system without active admin"""
    # Count current active admins
    current_admin_count = db.session.execute(
        select(func.count(User.id)).where(
            User.role == 'admin',
            User.state == True
        )
    ).scalar()
    
    user = db.session.get(User, user_id)
    if not user:
        return False, "User not found"
    
    # If this is the only active admin and we're trying to demote or deactivate
    if (user.role == 'admin' and user.state and current_admin_count <= 1):
        if (new_role and new_role != 'admin') or (new_state is not None and not new_state):
            return False, "Cannot modify the last active admin account"
    
    return True, ""

def _first_refusal(*checks):
    """First failing validator's refusal, or ``None`` when all pass.

    Thirteen call sites repeated `valid, error = check()` followed by the same
    400. Takes callables rather than results so evaluation still short-circuits
    — `check_username_unique` queries the database, and should not run when the
    username has already been rejected.
    """
    for check in checks:
        valid, error = check()
        if not valid:
            return api_error(error, code='bad_request')
    return None


@admin2_bp.route('/admin/users', methods=['GET'])
@login_required
@admin_required
def users_spa():
    return render_template('admin/admin_users.html')


# /admin/manage_users retired (GT-B18).
#
# Two editors for the same user rows meant two places to look and two
# behaviours to keep in step — the React roster at /admin/users is the one that
# is maintained, and it has had multi-select and the metric strip since GT-C2.
# The template and its CSS/JS are removed with it; the invites page now points
# at the roster.

@admin2_bp.route('/admin/api/users', methods=['GET'])
@login_required
@admin_required
def list_users_api():
    users = db.session.execute(select(User).order_by(User.name.asc())).scalars().all()
    return jsonify({
        'users': [
            {
                'id': u.id,
                # The placeholder is an implementation detail of the NOT NULL
                # constraint. Showing it in the roster would invite someone to
                # copy it into a mail client.
                'email': display_email(u.email) or '',
                'has_email': not is_placeholder_email(u.email),
                'name': u.name,
                'role': u.role,
                'state': bool(u.state),
                'is_email_verified': bool(u.is_email_verified),
                'about': u.about or '',
                'avatarpath': u.avatarpath or '',
            }
            for u in users
        ]
    })


@admin2_bp.route('/admin/api/user/<int:user_id>', methods=['GET', 'PUT', 'DELETE'])
@login_required
@admin_required
def manage_user_api(user_id):
    if request.method == 'PUT' and user_id == 0:  # Special case for new user creation
        data = request.json
        if not data:
            return api_error('No data provided', code='bad_request')
        
        # Validate required fields
        username = data.get('username', '').strip()
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        role = data.get('role', 'user')
        state = data.get('state', True)
        is_email_verified = data.get('is_email_verified', True)
        about = data.get('about', '')

        # An address is optional. A household account for a child's console or
        # the living-room TV has nowhere to send mail, and demanding one was
        # what stopped an admin creating that account at all. Without one the
        # user gets an unroutable placeholder — see utils/accounts.py — and is
        # never marked email-verified, because there is nothing to verify.
        emailless = not email
        if emailless:
            email = placeholder_email(username)
            is_email_verified = False

        # Input validation
        refusal = _first_refusal(
            lambda: validate_username(username),
            lambda: (True, "") if emailless else validate_email(email),
            lambda: validate_role(role),
            lambda: validate_about(about),
        )
        if refusal is not None:
            return refusal
        
        if not password:
            return api_error('Password is required', code='bad_request')
        
        # Type validation
        if not isinstance(state, bool):
            return api_error('State must be true or false', code='bad_request')
            
        if not isinstance(is_email_verified, bool):
            return api_error('Email verification status must be true or false', code='bad_request')
        
        # Uniqueness checks
        refusal = _first_refusal(
            lambda: check_username_unique(username),
            lambda: check_email_unique(email),
        )
        if refusal is not None:
            return refusal
        
        try:
            new_user = User(
                name=username,
                email=email,
                role=role,
                state=state,
                is_email_verified=is_email_verified,
                about=about if about else None,
                user_id=str(uuid4())
            )
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()
            log_system_event(
                f"Admin {current_user.name} created new user: {username} "
                f"(email: {'none — local account' if emailless else email}, role: {role})",
                event_type='audit',
                event_level='information',
            )
            return api_ok({
                'user': {
                    'id': new_user.id,
                    'name': new_user.name,
                    'email': display_email(new_user.email),
                    'has_email': not emailless,
                    'role': new_user.role,
                },
            })
        except IntegrityError as e:
            db.session.rollback()
            log_system_event(f"Admin {current_user.name} failed to create user {username}: Database integrity error", event_type='audit', event_level='error')
            return api_error('Username or email already exists', code='bad_request')
        except Exception as e:
            db.session.rollback()
            log_system_event(f"Admin {current_user.name} failed to create user {username}: {str(e)}", event_type='audit', event_level='error')
            return api_error('Failed to create user', code='internal')

    user = db.session.get(User, user_id)
    if not user:
        return api_error('User not found', code='not_found')
    
    if request.method == 'GET':
        content_filters = get_user_content_filters(user.id)
        return jsonify({
            'email': display_email(user.email) or '',
            'has_email': not is_placeholder_email(user.email),
            'role': user.role,
            'state': user.state,
            'about': user.about,
            'is_email_verified': user.is_email_verified,
            'allowed_library_uuids': get_user_library_allowlist(user.id),
            'denied_genres': content_filters['denied_genres'],
            'denied_themes': content_filters['denied_themes'],
        })
    
    elif request.method == 'PUT':
        # Enhanced permission checks
        if user_id == 1 and current_user.id != 1:
            return api_error('Cannot modify primary admin account', code='forbidden')
        
        # Prevent users from modifying their own role
        if current_user.id == user_id:
            data = request.json or {}
            if data.get('role') and data['role'] != user.role:
                return api_error('Cannot modify your own role', code='forbidden')
        
        data = request.json
        if not data:
            return api_error('No data provided', code='bad_request')
        
        # Track changes for audit logging
        changes = []
        old_values = {'email': user.email, 'role': user.role, 'state': user.state, 'is_email_verified': user.is_email_verified, 'about': user.about}
        
        # Validate and update email if provided
        if 'email' in data:
            new_email = (data['email'] or '').strip().lower()

            # The editor renders a placeholder address as an empty field, so an
            # unchanged emailless account comes back as ''. That must mean
            # "still no address", not "clear the column" — and clearing an
            # address the user does have is a real request, satisfied the same
            # way a new emailless account is.
            if not new_email:
                if not is_placeholder_email(user.email):
                    changes.append(f"email from '{user.email}' to none — local account")
                    user.email = placeholder_email(user.name)
                    user.is_email_verified = False
            elif new_email != (user.email or '').lower():
                valid, error = validate_email(new_email)
                if not valid:
                    return api_error(error, code='bad_request')

                valid, error = check_email_unique(new_email, exclude_user_id=user_id)
                if not valid:
                    return api_error(error, code='bad_request')

                previous = display_email(user.email) or 'none — local account'
                changes.append(f"email from '{previous}' to '{new_email}'")
                user.email = new_email
        
        # Validate and update role if provided
        if 'role' in data:
            new_role = data['role']
            if new_role != user.role:
                valid, error = validate_role(new_role)
                if not valid:
                    return api_error(error, code='bad_request')
                
                # Check admin protection before role change
                valid, error = check_admin_protection(user_id, new_role=new_role)
                if not valid:
                    return api_error(error, code='forbidden')
                
                changes.append(f"role from '{user.role}' to '{new_role}'")
                user.role = new_role
        
        # Validate and update state if provided
        if 'state' in data:
            new_state = data['state']
            if not isinstance(new_state, bool):
                return api_error('State must be true or false', code='bad_request')
            
            if new_state != user.state:
                # Check admin protection before state change
                valid, error = check_admin_protection(user_id, new_state=new_state)
                if not valid:
                    return api_error(error, code='forbidden')
                
                status = "active" if new_state else "inactive"
                changes.append(f"state to {status}")
                user.state = new_state
        
        # Validate and update email verification status if provided
        if 'is_email_verified' in data:
            new_verification = data['is_email_verified']
            if not isinstance(new_verification, bool):
                return api_error('Email verification status must be true or false', code='bad_request')
            
            if new_verification != user.is_email_verified:
                status = "verified" if new_verification else "unverified"
                changes.append(f"email verification to {status}")
                user.is_email_verified = new_verification
        
        # Validate and update about field if provided
        if 'about' in data:
            new_about = data['about']
            valid, error = validate_about(new_about)
            if not valid:
                return api_error(error, code='bad_request')
            
            if new_about != user.about:
                changes.append("about field")
                user.about = new_about
        
        # Handle password change
        if data.get('password'):
            password = data['password']
            if not isinstance(password, str) or not password.strip():
                return api_error('Invalid password provided', code='bad_request')
            user.set_password(password)
            changes.append("password")

        # Parental library allow-list (meaningful for child accounts)
        if 'allowed_library_uuids' in data:
            uuids = data.get('allowed_library_uuids') or []
            if not isinstance(uuids, list):
                return api_error('allowed_library_uuids must be a list', code='bad_request')
            set_user_library_allowlist(user.id, [str(u) for u in uuids])
            changes.append('library allow-list')

        if 'denied_genres' in data or 'denied_themes' in data:
            denied_genres = data.get('denied_genres')
            denied_themes = data.get('denied_themes')
            if denied_genres is not None and not isinstance(denied_genres, list):
                return api_error('denied_genres must be a list', code='bad_request')
            if denied_themes is not None and not isinstance(denied_themes, list):
                return api_error('denied_themes must be a list', code='bad_request')
            existing = get_user_content_filters(user.id)
            set_user_content_filters(
                user.id,
                denied_genres if denied_genres is not None else existing['denied_genres'],
                denied_themes if denied_themes is not None else existing['denied_themes'],
            )
            changes.append('content deny-list')
        
        try:
            db.session.commit()
            if 'password' in changes and user.id == current_user.id:
                # An admin changing their own password keeps this session.
                login_user(user, remember=True)

            # Log changes if any were made
            if changes:
                changes_str = ", ".join(changes)
                log_system_event(f"Admin {current_user.name} modified user {user.name}: {changes_str}", event_type='audit', event_level='information')
            
            return api_ok()
        except IntegrityError as e:
            db.session.rollback()
            log_system_event(f"Admin {current_user.name} failed to modify user {user.name}: Database integrity error", event_type='audit', event_level='error')
            return api_error('Email address already in use', code='bad_request')
        except Exception as e:
            db.session.rollback()
            log_system_event(f"Admin {current_user.name} failed to modify user {user.name}: {str(e)}", event_type='audit', event_level='error')
            return api_error('Failed to update user', code='internal')
    
    elif request.method == 'DELETE':
        # Enhanced admin protection
        if user_id == 1:
            return api_error('Cannot delete primary admin account', code='forbidden')
        
        # Prevent deleting the last active admin
        valid, error = check_admin_protection(user_id)
        if not valid:
            return api_error(error, code='forbidden')
        
        # Store user info for logging before deletion
        user_info = f"{user.name} (email: {user.email}, role: {user.role})"
        
        try:
            db.session.delete(user)
            db.session.commit()
            log_system_event(f"Admin {current_user.name} deleted user: {user_info}", event_type='audit', event_level='warning')
            return api_ok()
        except Exception as e:
            db.session.rollback()
            log_system_event(f"Admin {current_user.name} failed to delete user {user_info}: {str(e)}", event_type='audit', event_level='error')
            return api_error('Failed to delete user', code='internal')
