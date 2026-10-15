# oneirodex/routes_site.py
from flask import (
    Blueprint,
    redirect,
    url_for,
    current_app,
    send_from_directory,
    request,
    make_response,
)
from flask_login import login_required, logout_user, current_user

from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.utils.member_spa import render_member_spa
from oneirodex.utils.admin_spa import render_admin_spa
from oneirodex.utils.styleguide_page import render_styleguide

from sqlalchemy import func, select
from oneirodex import db
import os
import random
import re
from datetime import datetime
from oneirodex.models import Game, Library, Genre, Theme
from oneirodex.utils.auth import admin_required
from oneirodex.utils.library_acl import apply_game_access_filters

site_bp = Blueprint('site', __name__)

@site_bp.route('/dev/styleguide')
@login_required
@admin_required
def styleguide():
    """Every UI primitive, in every variant and state, on one page (GT-A6).

    This is the visual contract for the design system. Two vocabularies were
    live at once — 314 `.od-btn` call sites in the member SPA against 254
    Bootstrap `.btn` call sites in the Jinja pages — and nothing rendered them
    side by side, so nobody could see they had drifted apart. Rendering both
    families next to each other is the point: od-bootstrap-bridge.css claims
    they now look identical, and this page is where that claim is checkable.

    Admin-gated rather than debug-gated on purpose. Whether the active theme
    styles every primitive correctly is a question operators need to answer on
    their own install, with their own preset selected — not something only
    reachable in a dev checkout.
    """
    return render_styleguide()


@site_bp.route('/restricted')
@login_required
def restricted():
    return redirect(url_for('member.welcome_page'))


@site_bp.route('/help')
@login_required
def helpfaq():
    print("Route: /help")
    return render_member_spa(title='Help')

@site_bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login.login'))


@site_bp.route('/', methods=['GET', 'POST'])
@site_bp.route('/index', methods=['GET', 'POST'])
def index():
    from oneirodex.utils.setup import is_setup_required, is_setup_in_progress, get_setup_redirect_url
    
    # Check if setup is required or in progress
    if is_setup_required() or is_setup_in_progress():
        setup_url = get_setup_redirect_url()
        return redirect(setup_url)
        
    # If not authenticated, redirect to login
    if not current_user.is_authenticated:
        return redirect(url_for('login.login'))
        
    # If authenticated, redirect to discover page
    return redirect(url_for('discover.discover'))

@site_bp.route('/admin/dashboard')
@login_required
@admin_required
def admin_dashboard():
    print(f"Route: /admin/dashboard - {current_user.name} - {current_user.role} method: {request.method}")
    return render_admin_spa(title='Dashboard · Oneirodex Admin')


@site_bp.route('/admin/support')
@login_required
@admin_required
def admin_support():
    return render_admin_spa(title='Support inbox · Oneirodex Admin')


@site_bp.route('/favorites')
@login_required
def favorites():
    return render_member_spa()

@site_bp.route('/favicon.ico')
def favicon():
    """Browser fallback for /favicon.ico — Oneirodex mark from static/icons/."""
    full_dir = os.path.join(current_app.static_folder, 'icons')
    resp = make_response(
        send_from_directory(full_dir, 'favicon.ico', mimetype='image/vnd.microsoft.icon')
    )
    # Short TTL so post-rebrand browsers pick up the new mark without a hard purge.
    resp.headers['Cache-Control'] = 'public, max-age=3600'
    return resp


@site_bp.route('/trailers')
@login_required
def random_trailers():
    """Main page for watching random game trailers"""
    return render_member_spa(title='Trailers')


@site_bp.route('/api/trailers/filters')
@login_required
def get_filter_options():
    """API endpoint to get available filter options"""
    try:
        # Get all libraries
        libraries = db.session.execute(
            select(Library).order_by(Library.display_order, Library.name)
        ).scalars().all()

        # Get all genres
        genres = db.session.execute(
            select(Genre).order_by(Genre.name)
        ).scalars().all()

        # Get all themes
        themes = db.session.execute(
            select(Theme).order_by(Theme.name)
        ).scalars().all()

        # Get date range from games with videos
        date_range = db.session.execute(
            select(
                func.min(Game.first_release_date),
                func.max(Game.first_release_date)
            ).filter(
                Game.video_urls.isnot(None),
                Game.video_urls != '',
                Game.first_release_date.isnot(None)
            )
        ).first()

        min_year = date_range[0].year if date_range[0] else None
        max_year = date_range[1].year if date_range[1] else None

        return api_ok({
            'libraries': [{'uuid': str(lib.uuid), 'name': lib.name} for lib in libraries],
            'genres': [{'id': g.id, 'name': g.name} for g in genres],
            'themes': [{'id': t.id, 'name': t.name} for t in themes],
            'date_range': {
                'min_year': min_year,
                'max_year': max_year
            }
        })
    except Exception as e:
        current_app.logger.warning('Error fetching trailer filters: %s', e)
        return api_error('Failed to fetch filter options', code='internal')


@site_bp.route('/api/trailers/random')
@login_required
def get_random_trailer():
    """API endpoint to get a random game with trailer (with optional filters)"""
    try:
        # Select IDs only — DISTINCT on full Game rows fails on JSON columns (Postgres).
        query = select(Game.id).filter(
            Game.video_urls.isnot(None),
            Game.video_urls != ''
        )
        query = apply_game_access_filters(query, current_user)

        # Apply library filter
        library_uuid_param = request.args.get('library_uuid')
        if library_uuid_param:
            query = query.filter(Game.library_uuid == library_uuid_param)

        # Apply genre filter
        genres_param = request.args.get('genres')
        if genres_param:
            genre_ids = [int(gid) for gid in genres_param.split(',') if gid.strip()]
            if genre_ids:
                query = query.join(Game.genres).filter(Genre.id.in_(genre_ids))

        # Apply theme filter
        themes_param = request.args.get('themes')
        if themes_param:
            theme_ids = [int(tid) for tid in themes_param.split(',') if tid.strip()]
            if theme_ids:
                query = query.join(Game.themes).filter(Theme.id.in_(theme_ids))

        # Apply date range filters
        date_from_param = request.args.get('date_from')
        if date_from_param:
            try:
                date_from = datetime(int(date_from_param), 1, 1)
                query = query.filter(Game.first_release_date >= date_from)
            except (ValueError, TypeError):
                pass  # Invalid date format, skip filter

        date_to_param = request.args.get('date_to')
        if date_to_param:
            try:
                date_to = datetime(int(date_to_param), 12, 31)
                query = query.filter(Game.first_release_date <= date_to)
            except (ValueError, TypeError):
                pass  # Invalid date format, skip filter

        game_ids = db.session.execute(query.distinct()).scalars().all()

        if not game_ids:
            return api_ok({
                'has_videos': False,
                'empty': True,
                'code': 'no_trailers',
                'message': 'No games with trailers found matching your filters',
                'cta': {
                    'id': 'add_library',
                    'label': 'Add games to your library',
                    'href': '/admin/library/add',
                },
            })

        # Select a random game
        random_game = db.session.get(Game, random.choice(game_ids))
        if not random_game or not random_game.video_urls:
            return api_ok({
                'has_videos': False,
                'empty': True,
                'code': 'no_valid_urls',
                'message': 'No valid video URLs found',
                'cta': {
                    'id': 'add_library',
                    'label': 'Add games to your library',
                    'href': '/admin/library/add',
                },
            })

        # Parse video URLs (comma-separated)
        video_urls = [url.strip() for url in random_game.video_urls.split(',') if url.strip()]

        if not video_urls:
            # If somehow we got empty URLs, try another game
            return api_ok({
                'has_videos': False,
                'empty': True,
                'code': 'no_valid_urls',
                'message': 'No valid video URLs found',
                'cta': {
                    'id': 'add_library',
                    'label': 'Add games to your library',
                    'href': '/admin/library/add',
                },
            })

        # Pick a random video if multiple exist
        selected_video = random.choice(video_urls)

        # Convert YouTube watch URL to embed URL if needed
        embed_url = convert_to_embed_url(selected_video)

        # Return game data and video
        return api_ok({
            'has_videos': True,
            'game_uuid': random_game.uuid,
            'game_name': random_game.name,
            'video_url': embed_url
        })

    except Exception as e:
        current_app.logger.warning('Error fetching random trailer: %s', e)
        return api_error(
            'Error fetching trailer',
            code='internal',
            has_videos=False,
            empty=False,
        )


def convert_to_embed_url(video_url):
    """Convert YouTube URL to embed format with autoplay"""
    # Extract video ID from various YouTube URL formats
    youtube_patterns = [
        r'youtube\.com/watch\?v=([a-zA-Z0-9_-]+)',
        r'youtube\.com/embed/([a-zA-Z0-9_-]+)',
        r'youtu\.be/([a-zA-Z0-9_-]+)'
    ]

    for pattern in youtube_patterns:
        match = re.search(pattern, video_url)
        if match:
            video_id = match.group(1)
            return f"https://www.youtube.com/embed/{video_id}?autoplay=1&rel=0"

    # If already in embed format or unknown format, add autoplay parameter
    if 'autoplay' not in video_url:
        separator = '&' if '?' in video_url else '?'
        return f"{video_url}{separator}autoplay=1&rel=0"

    return video_url
