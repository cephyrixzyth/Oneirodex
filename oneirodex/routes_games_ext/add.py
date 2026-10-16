import os
from flask import redirect, url_for, flash, session, request, current_app
from flask_login import login_required, current_user
from oneirodex.forms import AddGameForm
from oneirodex.models import Game, Library, UnmatchedFolder, Category, Developer, Publisher
from oneirodex.utils.global_settings import global_settings_row
from oneirodex.utils.functions import read_first_nfo_content, igdb_platform_id_for, load_scanning_filter_patterns
from oneirodex.utils.auth import admin_required
from oneirodex.utils.scanning import refresh_images_in_background
from oneirodex.utils.event_logging import log_system_event
from oneirodex.utils.security import is_safe_path, get_allowed_base_directories, sanitize_path_for_logging
from oneirodex.utils.functions import sanitize_string_input
from oneirodex.utils.game_core import check_existing_game_by_igdb_id, ensure_manual_identify_taxonomy
from oneirodex.utils.gamenames import clean_game_name
from oneirodex.utils.game_name_parse import parse_game_label
from oneirodex.utils.item_kind import normalize_item_kind
from oneirodex import db
from oneirodex.utils.background import run_in_background
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select

from oneirodex.utils.admin_spa import render_admin_spa

from . import games_bp


@games_bp.route('/add_game_manual', methods=['GET', 'POST'])
@login_required
@admin_required
def add_game_manual():
    if request.method == 'GET':
        title = 'Identify unmatched folder' if request.args.get('from_unmatched') == 'true' else 'Identify game'
        return render_admin_spa(title=f'{title} · Oneirodex Admin')
    # Allow manual add / identify while a library scan is running (single-game update).
    full_disk_path = request.args.get('full_disk_path', None)
    library_uuid = request.args.get('library_uuid') or session.get('selected_library_uuid')
    from_unmatched = request.args.get('from_unmatched', 'false') == 'true'  # Detect origin
    raw_folder_name = os.path.basename(full_disk_path.rstrip('/\\')) if full_disk_path else ''
    # "Fix search": prefill the identify workbench with a scanner-cleaned title
    # (release-group tags / dots / underscores / VR-repack / build tails stripped)
    # instead of the raw folder name, so IGDB search actually finds a match on
    # the first try. Prefer soft UnmatchedFolder.search_name when set (Wave 17);
    # else parse_game_label's cleaned_name — it keeps original casing (e.g.
    # "Assassin's Creed") and applies the small alias map, unlike
    # clean_game_name's heavier pipeline which re-title-cases everything.
    soft_search = None
    if from_unmatched and full_disk_path:
        uf = db.session.execute(
            select(UnmatchedFolder).filter_by(folder_path=full_disk_path)
        ).scalars().first()
        if uf:
            soft_search = (getattr(uf, 'search_name', None) or '').strip() or None
    game_name = soft_search or raw_folder_name
    if raw_folder_name and not soft_search:
        try:
            cleaned_name = parse_game_label(raw_folder_name).get('cleaned_name') or ''
            if not cleaned_name:
                insensitive_patterns, sensitive_patterns = load_scanning_filter_patterns()
                cleaned_name = clean_game_name(raw_folder_name, insensitive_patterns, sensitive_patterns)
            if cleaned_name:
                game_name = cleaned_name
        except Exception as exc:
            log_system_event(
                f"Failed to clean folder name for identify search prefill: {exc}",
                event_type='form',
                event_level='warning'
            )

    form = AddGameForm()

    # Populate the choices for the library_uuid field
    form.library_uuid.choices = [(str(library.uuid), library.name) for library in db.session.execute(select(Library).order_by(Library.name)).scalars().all()]
    log_system_event(
        f"Add game form loaded with {len(form.library_uuid.choices)} library options",
        event_type='form',
        event_level='debug'
    )

    # Fetch library details for displaying on the form
    # Use the library_uuid already set from args or session (don't overwrite it!)
    library = db.session.execute(select(Library).filter_by(uuid=library_uuid)).scalars().first()
    if library:
        library_name = library.name
        platform_name = library.platform.name
        platform_id = igdb_platform_id_for(library.platform)
    else:
        library_name = platform_name = ''
        platform_id = None
    
    if request.method == 'GET':
        if full_disk_path:
            form.full_disk_path.data = full_disk_path
            form.name.data = game_name
        if library_uuid:
            form.library_uuid.data = library_uuid
        igdb_id_arg = request.args.get('igdb_id')
        if igdb_id_arg:
            try:
                form.igdb_id.data = int(igdb_id_arg)
            except (TypeError, ValueError):
                pass
    
    if form.validate_on_submit():
        # Validate full_disk_path security
        allowed_bases = get_allowed_base_directories(current_app)
        if not allowed_bases:
            flash('Service configuration error: No allowed base directories configured.', 'error')
            return render_admin_spa(title=('Identify unmatched folder' if request.args.get('from_unmatched') == 'true' else 'Identify game') + ' · Oneirodex Admin')

        is_safe, error_message = is_safe_path(form.full_disk_path.data, allowed_bases)
        if not is_safe:
            sanitized_path = sanitize_path_for_logging(form.full_disk_path.data)
            log_system_event(
                f"Path validation failed for admin {current_user.name}: {sanitized_path} - {error_message}",
                event_type='security',
                event_level='warning'
            )
            flash(f"Access denied: {error_message}", 'error')
            return render_admin_spa(title=('Identify unmatched folder' if request.args.get('from_unmatched') == 'true' else 'Identify game') + ' · Oneirodex Admin')

        # Check if this is a custom IGDB ID (above 2,000,000,420)
        is_custom_game = int(form.igdb_id.data) >= 2000000420
        
        # For custom games, skip IGDB ID check
        if not is_custom_game and check_existing_game_by_igdb_id(form.igdb_id.data):
            flash('A game with this IGDB ID already exists.', 'error')
            return render_admin_spa(title=('Identify unmatched folder' if request.args.get('from_unmatched') == 'true' else 'Identify game') + ' · Oneirodex Admin')
        
        new_game = Game(
            igdb_id=form.igdb_id.data,
            name=form.name.data,
            summary=form.summary.data,
            storyline=form.storyline.data,
            url=form.url.data,
            full_disk_path=form.full_disk_path.data,
            # Set default cover for custom games
            cover=url_for('static', filename='newstyle/default_cover.jpg') if is_custom_game else None,
            category=form.category.data,
            status=form.status.data,
            first_release_date=form.first_release_date.data,
            video_urls=form.video_urls.data,
            library_uuid=form.library_uuid.data
        )
        # Optional item_kind from form/query (game|experience|emulator|tool)
        kind_raw = request.form.get('item_kind') or request.args.get('item_kind')
        if kind_raw:
            new_game.item_kind = normalize_item_kind(kind_raw)
        elif is_custom_game:
            new_game.item_kind = 'game'
        new_game.genres = form.genres.data
        new_game.game_modes = form.game_modes.data
        new_game.themes = form.themes.data
        new_game.platforms = form.platforms.data
        new_game.player_perspectives = form.player_perspectives.data
        # Server-side IGDB taxonomy upsert (create-missing) so names absent from
        # the form checkbox list are not silently dropped on manual identify.
        if not is_custom_game:
            ensure_manual_identify_taxonomy(new_game, form.igdb_id.data)

        # Handle developer with input sanitization
        if form.developer.data and form.developer.data != 'Not Found':
            sanitized_developer_name = sanitize_string_input(form.developer.data, 255)
            if sanitized_developer_name:
                developer = db.session.execute(select(Developer).filter_by(name=sanitized_developer_name)).scalars().first()
                if not developer:
                    developer = Developer(name=sanitized_developer_name)
                    db.session.add(developer)
                    db.session.flush() 
                new_game.developer = developer

        # Handle publisher with input sanitization
        if form.publisher.data and form.publisher.data != 'Not Found':
            sanitized_publisher_name = sanitize_string_input(form.publisher.data, 255)
            if sanitized_publisher_name:
                publisher = db.session.execute(select(Publisher).filter_by(name=sanitized_publisher_name)).scalars().first()
                if not publisher:
                    publisher = Publisher(name=sanitized_publisher_name)
                    db.session.add(publisher)
                    db.session.flush()
                new_game.publisher = publisher
        new_game.nfo_content = read_first_nfo_content(form.full_disk_path.data)

        try:
            from oneirodex.utils.rom_language import apply_rom_language_fields

            apply_rom_language_fields(new_game, form.full_disk_path.data or form.name.data)
        except Exception:
            pass

        try:
            db.session.add(new_game)
            
            # Handle unmatched folder deletion in same transaction for consistency
            unmatched_folder = None
            if full_disk_path: 
                unmatched_folder = db.session.execute(select(UnmatchedFolder).filter_by(folder_path=full_disk_path)).scalars().first()
                if unmatched_folder:
                    db.session.delete(unmatched_folder)
            
            # Commit both operations together
            db.session.commit()

            # After successful commit, write local metadata file if enabled
            from oneirodex.utils.local_metadata import write_local_metadata
            from oneirodex.models import GlobalSettings

            settings = global_settings_row()
            print(f"[LOCAL METADATA] Settings check - settings exists: {settings is not None}, write_local_metadata: {settings.write_local_metadata if settings else 'N/A'}")

            if settings and settings.write_local_metadata:
                metadata_filename = settings.local_metadata_filename or 'oneirodex.json'
                success = write_local_metadata(
                    full_disk_path=form.full_disk_path.data,
                    igdb_id=form.igdb_id.data,
                    game_title=form.name.data,
                    manually_verified=True,
                    filename=metadata_filename
                )

                if success:
                    flash(f'Metadata file ({metadata_filename}) saved to game folder for future scans.', 'info')
                    log_system_event(
                        f"Local metadata written for game '{form.name.data}' at {sanitize_path_for_logging(form.full_disk_path.data)}",
                        event_type='metadata',
                        event_level='information'
                    )
                else:
                    flash(f'Warning: Could not write metadata file to game folder (check permissions).', 'warning')
                    log_system_event(
                        f"Failed to write local metadata for game '{form.name.data}' at {sanitize_path_for_logging(form.full_disk_path.data)}",
                        event_type='metadata',
                        event_level='warning'
                    )

            flash('Game added successfully.', 'success')
            log_system_event(
                f"Game '{game_name}' added manually by admin {current_user.name}" +
                (f" (removed from unmatched list)" if unmatched_folder else ""),
                event_type='game',
                event_level='information'
            )
            # Trigger image refresh after adding the game.
            #
            # The uuid is read here, not in the worker: `new_game` belongs to
            # this request's session, and the worker has its own
            # (utils/background.py). The old closure called `new_game.uuid`
            # from the thread, which is an ORM attribute load on a session
            # another thread was still using.
            new_game_uuid = new_game.uuid
            run_in_background(
                current_app._get_current_object(),
                refresh_images_in_background,
                new_game_uuid,
                name=f'oneirodex-refresh-images-{str(new_game_uuid)[:8]}',
            )
            log_system_event(
                f"Image refresh background task started for game '{game_name}' (UUID: {new_game.uuid})",
                event_type='task',
                event_level='debug'
            )
            
            if from_unmatched:
                return redirect(url_for('admin2.scan_management', active_tab='unmatched'))
            else:
                return redirect(url_for('library.library'))
        except SQLAlchemyError as e:
            db.session.rollback()
            log_system_event(
                f"Database error adding game '{game_name}' by admin {current_user.name}: {str(e)[:200]}",
                event_type='error',
                event_level='error'
            )
            flash('An error occurred while adding the game. Please try again.', 'error')
    else:
        if form.errors:
            log_system_event(
                f"Form validation failed for admin {current_user.name} adding game: {len(form.errors)} errors",
                event_type='form',
                event_level='warning'
            )
    return render_admin_spa(title=('Identify unmatched folder' if request.args.get('from_unmatched') == 'true' else 'Identify game') + ' · Oneirodex Admin')


@games_bp.route('/link_existing_game', methods=['POST'])
@login_required
@admin_required
def link_existing_game():
    """Link a disk folder being identified to an already-existing library game.

    Sets the chosen Game's full_disk_path to the folder currently being
    identified, clears the matching UnmatchedFolder row, and redirects back
    to the unmatched folders tab. Leaves the IGDB add flow untouched.
    """
    game_uuid = (request.form.get('game_uuid') or '').strip()
    full_disk_path = (request.form.get('full_disk_path') or '').strip()
    library_uuid = request.form.get('library_uuid') or None
    from_unmatched = request.form.get('from_unmatched', 'false') == 'true'

    def back_to_identify():
        return redirect(url_for(
            'games.add_game_manual',
            full_disk_path=full_disk_path or None,
            library_uuid=library_uuid,
            from_unmatched='true' if from_unmatched else 'false'
        ))

    if not game_uuid or not full_disk_path:
        flash('Select a game and a folder path before linking.', 'error')
        return back_to_identify()

    allowed_bases = get_allowed_base_directories(current_app)
    if not allowed_bases:
        flash('Service configuration error: No allowed base directories configured.', 'error')
        return back_to_identify()

    is_safe, error_message = is_safe_path(full_disk_path, allowed_bases)
    if not is_safe:
        sanitized_path = sanitize_path_for_logging(full_disk_path)
        log_system_event(
            f"Path validation failed for admin {current_user.name} linking existing game: {sanitized_path} - {error_message}",
            event_type='security',
            event_level='warning'
        )
        flash(f"Access denied: {error_message}", 'error')
        return back_to_identify()

    game = db.session.execute(select(Game).filter_by(uuid=game_uuid)).scalars().first()
    if not game:
        flash('Selected game could not be found.', 'error')
        return back_to_identify()

    try:
        game.full_disk_path = full_disk_path
        from oneirodex.utils.library_health import mark_game_path_ok

        mark_game_path_ok(game)
        try:
            from oneirodex.utils.rom_language import apply_rom_language_fields

            apply_rom_language_fields(game, full_disk_path)
        except Exception:
            pass

        unmatched_folder = db.session.execute(
            select(UnmatchedFolder).filter_by(folder_path=full_disk_path)
        ).scalars().first()
        if unmatched_folder:
            db.session.delete(unmatched_folder)

        db.session.commit()

        flash(f"Linked existing game '{game.name}' to this folder.", 'success')
        log_system_event(
            f"Admin {current_user.name} linked existing game '{game.name}' (UUID: {game.uuid}) to folder" +
            (" (removed from unmatched list)" if unmatched_folder else ""),
            event_type='game',
            event_level='information'
        )
    except SQLAlchemyError as e:
        db.session.rollback()
        log_system_event(
            f"Database error linking existing game '{game_uuid}' to folder by admin {current_user.name}: {str(e)[:200]}",
            event_type='error',
            event_level='error'
        )
        flash('An error occurred while linking the game. Please try again.', 'error')
        return back_to_identify()

    return redirect(url_for('admin2.scan_management', active_tab='unmatched'))
