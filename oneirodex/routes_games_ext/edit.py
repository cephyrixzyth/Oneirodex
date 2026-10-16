from flask import redirect, url_for, flash, request, abort, current_app
from flask_login import login_required, current_user
from oneirodex.forms import AddGameForm
from oneirodex.models import Game, Library, Category, Developer, Publisher, Status
from oneirodex.utils.functions import read_first_nfo_content, get_folder_size_in_bytes_updates, format_size, igdb_platform_id_for
from oneirodex.utils.auth import admin_required
from oneirodex.utils.scanning import refresh_images_in_background, is_scan_job_running
from oneirodex.utils.security import is_safe_path, get_allowed_base_directories, sanitize_path_for_logging
from oneirodex.utils.event_logging import log_system_event
from oneirodex.utils.game_core import ensure_manual_identify_taxonomy
from oneirodex.utils.game_provider_urls import apply_provider_urls, provider_url_fields
from oneirodex import db
from oneirodex.utils.background import run_in_background
from datetime import datetime, timezone
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy import select
from urllib.parse import urlparse
import re

from oneirodex.utils.admin_spa import render_admin_spa

from . import games_bp


@games_bp.route('/game_edit/<game_uuid>', methods=['GET', 'POST'])
@login_required
@admin_required
def game_edit(game_uuid):
    if request.method == 'GET':
        exists = db.session.execute(select(Game.id).filter_by(uuid=game_uuid)).scalar_one_or_none()
        if exists is None:
            abort(404)
        return render_admin_spa(title='Edit game entry · Oneirodex Admin')
    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first() or abort(404)
    form = AddGameForm(obj=game)
    form.library_uuid.choices = [(str(lib.uuid), lib.name) for lib in db.session.execute(select(Library).order_by(Library.name)).scalars().all()]
    platform_id = igdb_platform_id_for(game.library.platform)
    platform_name = game.library.platform.value
    library_name = game.library.name
    current_app.logger.debug(f"game_edit1 Platform ID: {platform_id}, Platform Name: {platform_name} Library Name: {library_name}")
    if form.validate_on_submit():
        # A scan rewrites the same rows this form is about to save, so an edit
        # landing mid-scan can be silently overwritten (or overwrite the scan's
        # own findings). Image upload/delete and game delete already refuse for
        # this reason; game_edit is the mutation that was left unguarded.
        if is_scan_job_running():
            flash('A scan is running. Editing games is available again as soon as it finishes.', 'error')
            return render_admin_spa(title='Edit game entry · Oneirodex Admin')

        # Validate full_disk_path security
        allowed_bases = get_allowed_base_directories(current_app)
        if not allowed_bases:
            flash('Service configuration error: No allowed base directories configured.', 'error')
            db.session.rollback()
            return render_admin_spa(title='Edit game entry · Oneirodex Admin')

        is_safe, error_message = is_safe_path(form.full_disk_path.data, allowed_bases)
        if not is_safe:
            current_app.logger.error(f"Security error: Game path validation failed for {sanitize_path_for_logging(form.full_disk_path.data)}: {error_message}")
            flash(f"Access denied: {error_message}", 'error')
            db.session.rollback()
            return render_admin_spa(title='Edit game entry · Oneirodex Admin')

        # Check if any other game has the same igdb_id and is not the current game (atomic check)
        try:
            # Use a more atomic approach - check within transaction context
            if form.igdb_id.data and form.igdb_id.data != game.igdb_id:
                existing_game_with_igdb_id = db.session.execute(select(Game).filter(
                    Game.igdb_id == form.igdb_id.data,
                    Game.id != game.id
                ).with_for_update()).scalars().first()
                
                if existing_game_with_igdb_id is not None:
                    flash(f'The IGDB ID {form.igdb_id.data} is already used by another game.', 'error')
                    db.session.rollback()
                    return render_admin_spa(title='Edit game entry · Oneirodex Admin')
        except SQLAlchemyError as e:
            current_app.logger.error(f"Database error during IGDB ID validation: {e}")
            flash('Database error during validation. Please try again.', 'error')
            db.session.rollback()
            return render_admin_spa(title='Edit game entry · Oneirodex Admin')
        
        igdb_id_changed = game.igdb_id != form.igdb_id.data
        
        # Validate and truncate field lengths
        game.library_uuid = form.library_uuid.data
        game.igdb_id = form.igdb_id.data
        
        # Validate name length (max 255)
        name = form.name.data or ""
        if len(name) > 255:
            name = name[:255]
            flash('Game name was truncated to 255 characters', 'warning')
        game.name = name
        
        # Validate text fields (max 4096)
        summary = form.summary.data or ""
        if len(summary) > 4096:
            summary = summary[:4096]
            flash('Summary was truncated to 4096 characters', 'warning')
        game.summary = summary
        
        storyline = form.storyline.data or ""
        if len(storyline) > 4096:
            storyline = storyline[:4096]
            flash('Storyline was truncated to 4096 characters', 'warning')
        game.storyline = storyline
        
        video_urls = form.video_urls.data or ""
        if len(video_urls) > 4096:
            video_urls = video_urls[:4096]
            flash('Video URLs were truncated to 4096 characters', 'warning')
        game.video_urls = video_urls
        
        # Validate URL field
        url = form.url.data or ""
        if url:
            if len(url) > 4096:
                url = url[:4096]
                flash('URL was truncated to 4096 characters', 'warning')
            try:
                parsed = urlparse(url)
                if parsed.scheme not in ['http', 'https']:
                    flash('URL must use http or https protocol', 'error')
                    db.session.rollback()
                    return render_admin_spa(title='Edit game entry · Oneirodex Admin')
                if not parsed.netloc:
                    flash('Invalid URL format', 'error')
                    db.session.rollback()
                    return render_admin_spa(title='Edit game entry · Oneirodex Admin')
            except Exception as e:
                current_app.logger.warning(f"URL validation error: {e}")
                flash('Invalid URL format', 'error')
                db.session.rollback()
                return render_admin_spa(title='Edit game entry · Oneirodex Admin')
        game.url = url
        
        game.full_disk_path = form.full_disk_path.data
        from oneirodex.utils.library_health import mark_game_path_ok

        mark_game_path_ok(game)
        try:
            from oneirodex.utils.rom_language import apply_rom_language_fields

            apply_rom_language_fields(game, form.full_disk_path.data or game.name)
        except Exception:
            pass
        game.aggregated_rating = form.aggregated_rating.data
        game.first_release_date = form.first_release_date.data

        # Validate and set status with proper error handling
        try:
            status_str = form.status.data
            if status_str:
                # Clean status string (remove 'Status.' prefix if present)
                status_str = status_str.replace('Status.', '').strip()
                # Validate against allowed enum values
                if status_str and status_str in Status.__members__:
                    game.status = Status[status_str]
                else:
                    current_app.logger.warning(f"Invalid status attempted: {status_str}")
                    flash(f'Invalid status: {status_str}', 'error')
                    db.session.rollback()
                    return render_admin_spa(title='Edit game entry · Oneirodex Admin')
        except (ValueError, AttributeError, KeyError) as e:
            current_app.logger.error(f"Status validation error: {e}")
            flash('Invalid status format', 'error')
            db.session.rollback()
            return render_admin_spa(title='Edit game entry · Oneirodex Admin')

        # Validate and set category with proper error handling
        try:
            category_str = form.category.data
            if category_str:
                # Clean category string
                category_str = category_str.replace('Category.', '').strip()
                # Validate against allowed enum values
                if category_str and category_str in Category.__members__:
                    game.category = Category[category_str]
                else:
                    current_app.logger.warning(f"Invalid category attempted: {category_str}")
                    flash(f'Invalid category: {category_str}', 'error')
                    db.session.rollback()
                    return render_admin_spa(title='Edit game entry · Oneirodex Admin')
        except (ValueError, AttributeError, KeyError) as e:
            current_app.logger.error(f"Category validation error: {e}")
            flash('Invalid category format', 'error')
            db.session.rollback()
            return render_admin_spa(title='Edit game entry · Oneirodex Admin')
        
        # Handling Developer with validation
        developer_name = form.developer.data
        if developer_name:
            # Validate developer name
            developer_name = developer_name.strip()
            if len(developer_name) > 255:
                flash('Developer name too long (max 255 characters)', 'error')
                db.session.rollback()
                return render_admin_spa(title='Edit game entry · Oneirodex Admin')
            if not developer_name:
                flash('Developer name cannot be empty', 'error')
                db.session.rollback()
                return render_admin_spa(title='Edit game entry · Oneirodex Admin')
            
            developer = db.session.execute(select(Developer).filter_by(name=developer_name)).scalars().first()
            if not developer:
                try:
                    developer = Developer(name=developer_name)
                    db.session.add(developer)
                    db.session.flush()
                except SQLAlchemyError as e:
                    current_app.logger.error(f"Error creating developer: {e}")
                    flash('Error creating developer', 'error')
                    db.session.rollback()
                    return render_admin_spa(title='Edit game entry · Oneirodex Admin')
            game.developer = developer

        # Handling Publisher with validation
        publisher_name = form.publisher.data
        if publisher_name:
            # Validate publisher name
            publisher_name = publisher_name.strip()
            if len(publisher_name) > 255:
                flash('Publisher name too long (max 255 characters)', 'error')
                db.session.rollback()
                return render_admin_spa(title='Edit game entry · Oneirodex Admin')
            if not publisher_name:
                flash('Publisher name cannot be empty', 'error')
                db.session.rollback()
                return render_admin_spa(title='Edit game entry · Oneirodex Admin')
            
            publisher = db.session.execute(select(Publisher).filter_by(name=publisher_name)).scalars().first()
            if not publisher:
                try:
                    publisher = Publisher(name=publisher_name)
                    db.session.add(publisher)
                    db.session.flush()
                except SQLAlchemyError as e:
                    current_app.logger.error(f"Error creating publisher: {e}")
                    flash('Error creating publisher', 'error')
                    db.session.rollback()
                    return render_admin_spa(title='Edit game entry · Oneirodex Admin')
            game.publisher = publisher

        # Update many-to-many relationships
        game.genres = form.genres.data
        game.game_modes = form.game_modes.data
        game.themes = form.themes.data
        game.platforms = form.platforms.data
        game.player_perspectives = form.player_perspectives.data
        # Server-side IGDB taxonomy upsert so Identify apply matches scan parity
        # (create-missing Genre/Theme/Platform/… instead of silent checkbox drop).
        try:
            igdb_numeric = int(form.igdb_id.data) if form.igdb_id.data is not None else None
        except (TypeError, ValueError):
            igdb_numeric = None
        if igdb_numeric is not None and igdb_numeric < 2000000420:
            ensure_manual_identify_taxonomy(game, igdb_numeric)
        
        # Updating size with error handling
        try:
            # Re-validate path before file operations
            is_safe, error_message = is_safe_path(game.full_disk_path, allowed_bases)
            if not is_safe:
                current_app.logger.error(f"Path validation failed during file operations: {error_message}")
                flash(f"Access denied: {error_message}", 'error')
                db.session.rollback()
                return render_admin_spa(title='Edit game entry · Oneirodex Admin')
            
            current_app.logger.info(f"Calculating folder size for {sanitize_path_for_logging(game.full_disk_path)}")
            new_folder_size_bytes = get_folder_size_in_bytes_updates(game.full_disk_path)
            current_app.logger.info(f"New folder size: {format_size(new_folder_size_bytes)}")
            game.size = new_folder_size_bytes
            
            # Safe NFO reading with error handling
            game.nfo_content = read_first_nfo_content(game.full_disk_path)
            
        except (OSError, PermissionError, FileNotFoundError) as e:
            current_app.logger.error(f"File operation error for path {sanitize_path_for_logging(game.full_disk_path)}: {e}")
            flash('Error accessing game files. Please check permissions.', 'error')
            db.session.rollback()
            return render_admin_spa(title='Edit game entry · Oneirodex Admin')
        except Exception as e:
            current_app.logger.error(f"Unexpected error during file operations: {e}")
            flash('Error processing game files', 'error')
            db.session.rollback()
            return render_admin_spa(title='Edit game entry · Oneirodex Admin')
        # Provider links ride the same commit as the rest of the edit, so a
        # failure below leaves them exactly as they were.
        apply_provider_urls(game, request.form)

        game.date_identified = datetime.now(timezone.utc)

        try:
            db.session.commit()
            log_system_event(f"Game {game.name} updated by admin {current_user.name}", event_type='game', event_level='information')

            if igdb_id_changed:
                # Single flash message that will show progress spinner via JavaScript
                flash('Game updated, downloading images', 'image-refresh')
                # Own app context, own session (utils/background.py). `game_uuid`
                # is already a plain string from the route, so nothing loaded in
                # this request crosses into the worker.
                run_in_background(
                    current_app._get_current_object(),
                    refresh_images_in_background,
                    game_uuid,
                    name=f'oneirodex-refresh-images-{str(game_uuid)[:8]}',
                )
                current_app.logger.info(f"Refresh images thread started for game UUID: {game_uuid}")
                # Store game_uuid in session so JavaScript can track progress
                from flask import session
                session['image_refresh_game_uuid'] = game_uuid
            else:
                flash('Game updated successfully.', 'success')
                current_app.logger.debug(f"IGDB ID unchanged. Skipping image refresh for game UUID: {game_uuid}")

            return redirect(url_for('library.library'))
        except IntegrityError as e:
            db.session.rollback()
            current_app.logger.error(f"Database integrity error: {e}")
            flash('Database integrity error. Please check for duplicate values.', 'error')
            return render_admin_spa(title='Edit game entry · Oneirodex Admin')
        except SQLAlchemyError as e:
            db.session.rollback()
            current_app.logger.error(f"Database error during commit: {e}")
            flash('An error occurred while updating the game. Please try again.', 'error')
            return render_admin_spa(title='Edit game entry · Oneirodex Admin')

    if request.method == 'POST':
        current_app.logger.warning(f"/game_edit/: Form validation failed: {form.errors}")

    # For GET or if form fails
    current_app.logger.debug(f"game_edit2 Platform ID: {platform_id}, Platform Name: {platform_name}, Library Name: {library_name}")
    return render_admin_spa(title='Edit game entry · Oneirodex Admin')
