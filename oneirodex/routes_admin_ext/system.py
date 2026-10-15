from oneirodex.utils.api_response import api_error, api_ok
from flask import current_app, redirect, request, jsonify, session, url_for
from flask_login import login_required, current_user
from oneirodex.product import RESET_CONFIRM_PHRASE, is_reset_confirm
from oneirodex.utils.auth import admin_required
from oneirodex.utils.admin_spa import render_admin_spa
from oneirodex.models import SystemEvents, DiscoverySection, Game, Genre, Library, user_favorites
from oneirodex import db
from oneirodex.platform import LibraryPlatform
from oneirodex.schemas.admin_system import (
    DiscoveryShelfBody,
    UpdateSectionOrderBody,
    UpdateSectionVisibilityBody,
)
from oneirodex.utils.event_logging import log_system_event
from oneirodex.utils.discovery_shelves import (
    count_custom_shelf_games,
    describe_shelf_config,
    validate_shelf_config,
)
from oneirodex.utils.discovery_sections import (
    discovery_section_public,
    discovery_sections_data,
    utc_naive as _utc_naive,
)
from oneirodex.utils.validation import validate_body
from sqlalchemy import select, and_, func
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import uuid
from . import admin2_bp

# Constants
DEFAULT_PER_PAGE = 50
MAX_PER_PAGE = 200
DATE_FORMAT = '%Y-%m-%d'


def validate_pagination_params(page: int, per_page: int) -> tuple[int, int]:
    """Validate and sanitize pagination parameters."""
    page = max(1, page)  # Ensure page is at least 1
    per_page = min(max(1, per_page), MAX_PER_PAGE)  # Clamp per_page between 1 and MAX_PER_PAGE
    return page, per_page


def parse_date_filter(date_str: Optional[str]) -> Optional[datetime]:
    """Parse date string and return datetime object or None if invalid."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, DATE_FORMAT)
    except ValueError:
        return None


def validate_json_request(data: Dict[str, Any], required_fields: list[str]) -> tuple[bool, Optional[str]]:
    """Validate JSON request data for required fields."""
    if data is None:
        return False, "No JSON data provided"
    
    for field in required_fields:
        if field not in data:
            return False, f"Missing required field: {field}"
    
    return True, None

@admin2_bp.route('/admin/system_logs')
@admin2_bp.route('/admin/server_logs')
@login_required
@admin_required
def system_logs():
    """Redirect bookmarks to Ops Full-log popup (UID-034).

    Canonical path: ``/admin/system_logs``. Alias ``/admin/server_logs`` kept so
    old LHN / docs links do not 404. The browse UI lives on Ops now.
    """
    return redirect(url_for('info.admin_ops', open='full-log'))

@admin2_bp.route('/admin/discovery_sections')
@login_required
@admin_required
def discovery_sections():
    return render_admin_spa(title='Discovery sections · Oneirodex Admin')


@admin2_bp.route('/admin/api/discovery_sections', methods=['GET'])
@login_required
@admin_required
def discovery_sections_state_api():
    try:
        data = discovery_sections_data()
        response = current_app.make_response(api_ok({
            'sections': [discovery_section_public(section, data) for section in data['sections']],
            'libraries': [{'uuid': row.uuid, 'name': row.name} for row in data['libraries']],
            'platforms': [{'id': row.name, 'label': row.value} for row in data['platforms']],
            'genres': [{'name': row.name} for row in data['genres']], 'max_games': 60,
        }))
        response.headers['Cache-Control'] = 'no-store'
        return response
    except Exception:
        return api_error('Could not load discovery sections', code='internal')


@admin2_bp.route('/admin/api/discovery_sections', methods=['POST'])
@login_required
@admin_required
@validate_body(DiscoveryShelfBody)
def create_discovery_section(body: DiscoveryShelfBody) -> tuple[Dict[str, Any], int]:
    """Create a custom discovery shelf (manual game pick list or library/platform/genre filter)."""
    try:
        name = body.name
        if len(name) > 50:
            return api_error('Shelf name must be 50 characters or fewer', code='bad_request')

        config, error = validate_shelf_config(
            body.mode,
            game_uuids=body.game_uuids,
            filter_type=body.filter_type,
            filter_value=body.filter_value,
        )
        if error:
            return api_error(error, code='bad_request')

        max_order = db.session.execute(select(func.max(DiscoverySection.display_order))).scalar() or 0
        identifier = f"custom_{uuid.uuid4().hex[:12]}"

        section = DiscoverySection(
            name=name,
            identifier=identifier,
            is_visible=True,
            display_order=max_order + 1,
            section_type='custom',
            config=config,
        )
        db.session.add(section)
        db.session.commit()

        log_system_event(
            f"Created custom discovery shelf '{name}'",
            event_type='admin_action',
            event_level='information',
            audit_user=current_user.id,
        )

        return api_ok({
                        'section': {
                'id': section.id,
                'name': section.name,
                'identifier': section.identifier,
                'is_visible': section.is_visible,
                'section_type': section.section_type,
                'description': describe_shelf_config(section.config),
                'count': count_custom_shelf_games(section.config),
            },
        }, status=201)

    except Exception as e:
        db.session.rollback()
        log_system_event(
            f"Failed to create discovery shelf: {str(e)}",
            event_type='admin_action',
            event_level='error',
            audit_user=current_user.id,
        )
        return api_error('Internal server error', code='internal')


@admin2_bp.route('/admin/api/discovery_sections/<int:section_id>', methods=['PUT'])
@login_required
@admin_required
@validate_body(DiscoveryShelfBody)
def update_discovery_section(section_id: int, body: DiscoveryShelfBody) -> tuple[Dict[str, Any], int]:
    """Edit a custom discovery shelf's name and/or selection."""
    try:
        section = db.session.get(DiscoverySection, section_id)
        if not section:
            return api_error('Shelf not found', code='not_found')
        if section.section_type != 'custom':
            return api_error('Only custom shelves can be edited', code='bad_request')

        name = body.name
        if len(name) > 50:
            return api_error('Shelf name must be 50 characters or fewer', code='bad_request')

        config, error = validate_shelf_config(
            body.mode,
            game_uuids=body.game_uuids,
            filter_type=body.filter_type,
            filter_value=body.filter_value,
        )
        if error:
            return api_error(error, code='bad_request')

        section.name = name
        section.config = config
        db.session.commit()

        log_system_event(
            f"Updated custom discovery shelf '{name}'",
            event_type='admin_action',
            event_level='information',
            audit_user=current_user.id,
        )

        return api_ok({
                        'section': {
                'id': section.id,
                'name': section.name,
                'identifier': section.identifier,
                'is_visible': section.is_visible,
                'section_type': section.section_type,
                'description': describe_shelf_config(section.config),
                'count': count_custom_shelf_games(section.config),
            },
        })

    except Exception as e:
        db.session.rollback()
        log_system_event(
            f"Failed to update discovery shelf {section_id}: {str(e)}",
            event_type='admin_action',
            event_level='error',
            audit_user=current_user.id,
        )
        return api_error('Internal server error', code='internal')


@admin2_bp.route('/admin/api/discovery_sections/<int:section_id>/schedule', methods=['PUT'])
@login_required
@admin_required
def update_discovery_section_schedule(section_id: int) -> tuple[Dict[str, Any], int]:
    """Set a shelf's storefront layout and its optional event window (W25-STORE-1).

    Applies to **every** shelf, not just custom shelves: running a seed shelf like
    "Upcoming" as a limited-time feature is the whole point of the schedule.

    Body: ``layout`` (shelf|hero|carousel), ``starts_at`` / ``ends_at``
    (ISO 8601, or null to clear).
    """
    section = db.session.get(DiscoverySection, section_id)
    if not section:
        return api_error('Shelf not found', code='not_found')

    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not data or set(data) - {'layout', 'starts_at', 'ends_at'}:
        return api_error('Provide only layout and schedule fields', code='bad_request')
    layout = section.layout
    starts = _utc_naive(section.starts_at) if section.starts_at else None
    ends = _utc_naive(section.ends_at) if section.ends_at else None

    if 'layout' in data:
        raw_layout = data.get('layout')
        if not isinstance(raw_layout, str):
            return api_error('layout must be shelf, hero, or carousel', code='bad_request')
        layout = (raw_layout or 'shelf').strip().lower()
        if layout not in ('shelf', 'hero', 'carousel'):
            return api_error(
                'layout must be shelf, hero, or carousel',
                code='bad_request',
            )

    def _parse(key):
        raw = data.get(key)
        if raw in (None, ''):
            return None, None
        try:
            if not isinstance(raw, str):
                raise ValueError
            return _utc_naive(datetime.fromisoformat(raw.replace('Z', '+00:00'))), None
        except (ValueError, TypeError):
            return None, f'{key} must be an ISO timestamp'

    if 'starts_at' in data:
        value, error = _parse('starts_at')
        if error:
            return api_error(error, code='bad_request')
        starts = value
    if 'ends_at' in data:
        value, error = _parse('ends_at')
        if error:
            return api_error(error, code='bad_request')
        ends = value

    # A window that closes before it opens would silently hide the shelf forever.
    if starts and ends and ends <= starts:
        return api_error('ends_at must be after starts_at', code='bad_request')

    section.layout = layout
    section.starts_at = starts
    section.ends_at = ends

    try:
        db.session.commit()
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        log_system_event(
            f'Failed to update shelf schedule {section_id}: {exc}',
            event_type='admin_action',
            event_level='error',
            audit_user=current_user.id,
        )
        return api_error('Internal server error', code='internal')

    return api_ok({
                'section': {
            'id': section.id,
            'name': section.name,
            'identifier': section.identifier,
            'layout': section.layout,
            'starts_at': section.starts_at.isoformat() if section.starts_at else None,
            'ends_at': section.ends_at.isoformat() if section.ends_at else None,
            'is_live': section.is_live(),
        },
    })


@admin2_bp.route('/admin/api/discovery_sections/<int:section_id>/pin', methods=['PUT'])
@login_required
@admin_required
def update_discovery_section_pin(section_id: int) -> tuple[Dict[str, Any], int]:
    """Force a shelf into the reserved block at the top of every member's feed.

    Body: ``pin_rank`` — a number (lowest first), or null to release the shelf
    back to its ``display_order`` position.

    Only the first three forced shelves take effect. The cap is deliberate: a
    member gets three pins of their own, and an admin who could force ten would
    push every member's pins below the fold on their own home page.
    """
    section = db.session.get(DiscoverySection, section_id)
    if not section:
        return api_error('Shelf not found', code='not_found')

    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != {'pin_rank'}:
        return api_error('Provide a pin rank or null', code='bad_request')
    raw = data.get('pin_rank')
    if raw in (None, ''):
        section.pin_rank = None
    else:
        if type(raw) is not int or not -(2 ** 31) <= raw < 2 ** 31:
            return api_error('pin_rank must be a whole number or null', code='bad_request')
        section.pin_rank = raw

    try:
        db.session.commit()
    except Exception as exc:  # noqa: BLE001
        db.session.rollback()
        log_system_event(
            f'Failed to update shelf pin {section_id}: {exc}',
            event_type='admin_action',
            event_level='error',
            audit_user=current_user.id,
        )
        return api_error('Internal server error', code='internal')

    log_system_event(
        (
            f"Released shelf '{section.name}' from the top block"
            if section.pin_rank is None
            else f"Forced shelf '{section.name}' to the top block at rank {section.pin_rank}"
        ),
        event_type='admin_action',
        event_level='information',
        audit_user=current_user.id,
    )

    return api_ok({
        'section': {
            'id': section.id,
            'identifier': section.identifier,
            'name': section.name,
            'pin_rank': section.pin_rank,
        },
    })


@admin2_bp.route('/admin/api/discovery_sections/<int:section_id>', methods=['DELETE'])
@login_required
@admin_required
def delete_discovery_section(section_id: int) -> tuple[Dict[str, Any], int]:
    """Delete a custom discovery shelf. Seed shelves cannot be deleted."""
    try:
        section = db.session.get(DiscoverySection, section_id)
        if not section:
            return api_error('Shelf not found', code='not_found')
        if section.section_type != 'custom':
            return api_error('Only custom shelves can be deleted', code='bad_request')

        name = section.name
        db.session.delete(section)
        db.session.commit()

        log_system_event(
            f"Deleted custom discovery shelf '{name}'",
            event_type='admin_action',
            event_level='information',
            audit_user=current_user.id,
        )

        return api_ok({'message': f"Shelf '{name}' deleted"})

    except Exception as e:
        db.session.rollback()
        log_system_event(
            f"Failed to delete discovery shelf {section_id}: {str(e)}",
            event_type='admin_action',
            event_level='error',
            audit_user=current_user.id,
        )
        return api_error('Internal server error', code='internal')

@admin2_bp.route('/admin/api/discovery_sections/order', methods=['POST'])
@login_required
@admin_required
@validate_body(UpdateSectionOrderBody)
def update_section_order(body: UpdateSectionOrderBody) -> tuple[Dict[str, Any], int]:
    """
    Update the display order of discovery sections.
    
    Expected JSON payload:
    {
        "sections": [
            {"id": 1, "order": 1},
            {"id": 2, "order": 2},
            ...
        ]
    }
    """
    try:
        updated_sections = []
        staged = []
        ids = set()
        for item in body.sections:
            if item.id in ids:
                return api_error('Section IDs must be unique', code='bad_request')
            ids.add(item.id)
            if item.order < 0:
                return api_error('Display order must be non-negative', code='bad_request')

            section = db.session.get(DiscoverySection, item.id)
            if not section:
                return api_error(f'Section with ID {item.id} not found', code='not_found')

            staged.append((section, item.order))
            updated_sections.append(section.name)
        for section, order in staged:
            section.display_order = order
        
        db.session.commit()
        
        # Log the action for audit trail
        log_system_event(
            f"Updated display order for {len(updated_sections)} discovery sections: {', '.join(updated_sections)}",
            event_type='admin_action',
            event_level='information',
            audit_user=current_user.id
        )
        
        return api_ok({
                        'message': f'Updated order for {len(updated_sections)} sections',
            'updated_sections': updated_sections
        })
        
    except Exception as e:
        db.session.rollback()
        log_system_event(
            f"Failed to update discovery section order: {str(e)}",
            event_type='admin_action',
            event_level='error',
            audit_user=current_user.id
        )
        return api_error('Internal server error', code='internal')

@admin2_bp.route('/admin/api/discovery_sections/visibility', methods=['POST'])
@login_required
@admin_required
@validate_body(UpdateSectionVisibilityBody)
def update_section_visibility(body: UpdateSectionVisibilityBody) -> tuple[Dict[str, Any], int]:
    """
    Update the visibility status of a discovery section.
    
    Expected JSON payload:
    {
        "section_id": 1,
        "is_visible": true
    }
    """
    try:
        section = db.session.get(DiscoverySection, body.section_id)
        if not section:
            return api_error(f'Section with ID {body.section_id} not found', code='not_found')

        old_visibility = section.is_visible
        section.is_visible = body.is_visible

        db.session.commit()

        visibility_status = 'visible' if body.is_visible else 'hidden'
        log_system_event(
            f"Changed discovery section '{section.name}' visibility to {visibility_status}",
            event_type='admin_action',
            event_level='information',
            audit_user=current_user.id
        )

        return api_ok({
                        'message': f"Section '{section.name}' is now {'visible' if body.is_visible else 'hidden'}",
            'section_name': section.name,
            'old_visibility': old_visibility,
            'new_visibility': body.is_visible
        })
        
    except Exception as e:
        db.session.rollback()
        log_system_event(
            f"Failed to update discovery section visibility: {str(e)}",
            event_type='admin_action',
            event_level='error',
            audit_user=current_user.id
        )
        return api_error('Internal server error', code='internal')

@admin2_bp.route('/admin/api/system_logs/clear', methods=['DELETE'])
@login_required
@admin_required
def clear_system_logs() -> tuple[Dict[str, Any], int]:
    """
    Clear all system logs from the database.
    
    This is a destructive action that cannot be undone.
    The action is logged after clearing the logs for audit purposes.
    """
    try:
        # Get count of logs before deletion for the response
        logs_count = db.session.execute(select(db.func.count(SystemEvents.id))).scalar()
        
        # Delete all system events
        db.session.execute(db.delete(SystemEvents))
        db.session.commit()
        
        # Log the action after clearing logs so it persists
        log_system_event(
            f"System logs cleared by admin user '{current_user.name}' (ID: {current_user.id}). {logs_count} logs were deleted.",
            event_type='admin_action',
            event_level='warning',
            audit_user=current_user.id
        )
        
        return api_ok({
                        'message': f'Successfully cleared {logs_count} system logs',
            'deleted_count': logs_count
        })
        
    except Exception as e:
        db.session.rollback()
        log_system_event(
            f"Failed to clear system logs: {str(e)}",
            event_type='admin_action',
            event_level='error',
            audit_user=current_user.id
        )
        return api_error('Internal server error', code='internal')


@admin2_bp.route('/admin/clear_permission_errors', methods=['POST'])
@login_required
@admin_required
def clear_permission_errors() -> tuple[Dict[str, Any], int]:
    """Drop the scan write-permission failure payload after its modal is shown.

    Set by the scan path in ``utilities.py`` when a library path is not writable;
    without this the flags persist for the rest of the session and the modal
    re-opens on later visits.
    """
    for key in ('permission_check_failed', 'permission_errors', 'permission_check_path'):
        session.pop(key, None)
    return api_ok()


# --- System reset (danger zone) --------------------------------------------
#
# The confirmation phrase is required in the request body rather than being a
# UI-only guard. A destructive endpoint that any authenticated admin can fire
# with an empty POST is one stray fetch away from an accident, and "the button
# asks first" is not a property of the API. Phrase lives in oneirodex.product
# (RESET ONEIRODEX, with RESET ONEIRODEX still accepted).


@admin2_bp.route('/admin/api/system/reset', methods=['POST'])
@login_required
@admin_required
def system_reset_plan_or_perform():
    """Preview or carry out a scoped factory reset.

    ``POST {"scopes": [...]}`` returns the plan — every table that would be
    emptied, including those reached by cascade — and changes nothing.

    ``POST {"scopes": [...], "confirm": "RESET ONEIRODEX"}`` performs it.
    ``RESET ONEIRODEX`` remains accepted so existing runbooks keep working.

    Never deletes files. See oneirodex/utils/system_reset.py.
    """
    from oneirodex.utils.system_reset import RESET_SCOPES, expand_scopes, perform_reset, plan_reset

    data = request.get_json(silent=True) or {}
    requested = data.get('scopes')
    if not isinstance(requested, list) or not requested:
        return api_error(
            'Choose at least one thing to reset.',
            code='bad_request',
            detail={'valid_scopes': sorted(RESET_SCOPES)},
        )

    unknown = [s for s in requested if s not in RESET_SCOPES]
    if unknown:
        return api_error(
            f'Unknown reset scope: {", ".join(sorted(unknown))}.',
            code='bad_request',
            detail={'valid_scopes': sorted(RESET_SCOPES)},
        )

    confirm = data.get('confirm')
    if confirm is None:
        # Preview. Deliberately the default: a caller that forgets the phrase
        # gets a description of the damage, not the damage.
        return api_ok(plan_reset(requested), performed=False)

    if not is_reset_confirm(confirm):
        return api_error(
            f'Type "{RESET_CONFIRM_PHRASE}" exactly to confirm.',
            code='unprocessable',
        )

    scopes = expand_scopes(requested)
    # Logged *before* the reset: the settings scope truncates system_events, so
    # an entry written afterwards would be the only row in an otherwise empty
    # audit log, and one written inside would be erased by its own operation.
    log_system_event(
        f"System reset requested (scopes: {', '.join(scopes)})",
        event_type='admin_action',
        event_level='warning',
        audit_user=current_user.id,
    )

    try:
        result = perform_reset(scopes, actor_user_id=current_user.id)
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception('System reset failed')
        return api_error(
            'Reset failed and nothing was changed.',
            code='internal',
            detail={'reason': type(exc).__name__},
        )

    return api_ok(result)
