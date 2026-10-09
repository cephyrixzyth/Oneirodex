"""
Centralized Initialization Manager for Oneirodex.
This module consolidates all initialization logic into a single, coordinated system
that ensures proper startup order and eliminates duplication.
"""

import os
import shutil
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

from oneirodex.utils.preset_themes import (
    install_preset_themes,
    sync_preset_themes,
    sync_theme_tree,
)
from oneirodex.utils.icon_themes import install_icon_themes
from oneirodex.utils.library_paths import library_dir, seed_shipped_library

# Everything the app ships or generates lives inside the package, so paths must
# be resolved from here rather than from the process working directory (under
# Docker/uvicorn the CWD is not the repo root).
PACKAGE_ROOT = os.path.dirname(os.path.abspath(__file__))


def _safe_print(*args, **kwargs):
    """Print without raising on Windows cp1252 consoles."""
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        import sys
        encoding = getattr(sys.stdout, 'encoding', None) or 'ascii'
        cleaned = []
        for arg in args:
            if isinstance(arg, str):
                cleaned.append(
                    arg.encode(encoding, errors='replace').decode(
                        encoding, errors='replace'
                    )
                )
            else:
                cleaned.append(arg)
        print(*cleaned, **kwargs)




class InitializationManager:
    """Central coordinator for all Oneirodex initialization tasks."""

    def __init__(self):
        self._environment_loaded = False
        self._initialization_complete = False

    def run_complete_initialization(self):
        """
        Master orchestrator for all initialization phases.
        Returns True on success, False on failure.
        """
        try:
            _safe_print("[..] Starting Oneirodex initialization...")

            # Phase 1: Environment setup (load once)
            _safe_print("\nCHAPTER 1/5 // Beneath black water, Onei's eyes wake on their stalks.")
            if not self._phase1_environment():
                return False
            _safe_print("TITAN NOTE // The waking air is safe to breathe.")

            # Phase 2: Database structure (tables and migrations)
            _safe_print("\nCHAPTER 2/5 // Onei follows the old runes across the memory bridge.")
            if not self._phase2_database_structure():
                return False
            _safe_print("TITAN NOTE // The world's ledger answers the call.")

            # Phase 3: Default data initialization
            _safe_print("\nCHAPTER 3/5 // The titan gathers lost sparks to kindle the first dawn.")
            if not self._phase3_default_data():
                return False
            _safe_print("TITAN NOTE // The starting constellations shine again.")

            # Phase 4: Filesystem setup (folders and themes)
            _safe_print("\nCHAPTER 4/5 // Onei's many legs find safe paths through the sleeping worlds.")
            if not self._phase4_filesystem():
                return False
            _safe_print("TITAN NOTE // The worlds have paths, homes, and colors.")

            # Phase 5: Cleanup and finalization
            _safe_print("\nCHAPTER 5/5 // Onei folds its mighty pincers and guards the launch gate.")
            if not self._phase5_cleanup():
                return False
            _safe_print("TITAN NOTE // The dream is clear; Onei is ready to stand watch.")

            self._initialization_complete = True
            _safe_print("[OK] Oneirodex initialization completed successfully")
            return True

        except Exception as e:
            _safe_print(f"[ERR] Initialization failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _phase1_environment(self):
        """Load environment variables exactly once."""
        if self._environment_loaded:
            _safe_print("Environment variables already loaded")
            return True

        try:
            # Use explicit path to ensure .env is found
            from pathlib import Path
            import os
            env_path = Path(__file__).parent.parent / '.env'

            load_dotenv(dotenv_path=env_path)
            self._environment_loaded = True

            # Debug: Verify critical environment variables are loaded
            database_url = os.getenv('DATABASE_URL')
            if database_url:
                # Mask password for security
                masked_url = database_url.split('@')[0].split(':')[0:2]
                masked_url = ':'.join(masked_url) + ':***@' + database_url.split('@')[1] if '@' in database_url else database_url
                _safe_print("Environment variables loaded successfully")
                _safe_print(f"DATABASE_URL found: {masked_url}")
            else:
                _safe_print("[WARN] DATABASE_URL not found in environment - using config fallback")

            return True
        except Exception as e:
            _safe_print(f"[ERR] Failed to load environment: {e}")
            return False

    def _phase2_database_structure(self):
        """Create database tables and run migrations."""
        _safe_print("Phase 2: Database structure setup")

        try:
            # Import config after environment is loaded
            from config import Config

            # Create tables using pure SQLAlchemy
            engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)

            try:
                # Import models to register them with SQLAlchemy
                from oneirodex import models

                # Create all tables (idempotent operation)
                models.db.metadata.create_all(engine)
                _safe_print("[OK] Database tables created")

                # Run schema migrations
                from oneirodex.updateschema import DatabaseManager
                db_manager = DatabaseManager()
                db_manager.add_column_if_not_exists()
                _safe_print("[OK] Database migrations completed")

                # Alembic owns forward schema change (wave A3.1). Pre-Alembic
                # DBs are stamped at the baseline revision (schema already
                # present via create_all + updateschema); every boot then runs
                # `alembic upgrade head` so post-baseline revisions (e.g.
                # schedule columns) land without a manual operator step.
                self._ensure_alembic_current(engine)

            finally:
                engine.dispose()

            return True

        except Exception as e:
            _safe_print(f"[ERR] Database structure setup failed: {e}")
            return False

    # First squashed Alembic revision (create_all + frozen updateschema).
    _ALEMBIC_BASELINE_REVISION = 'b9ab856b09ff'

    def _ensure_alembic_current(self, engine):
        """Adopt pre-Alembic DBs at baseline, then upgrade to head.

        - No ``alembic_version`` + existing schema -> stamp baseline only
          (never ``head``: that would skip post-baseline DDL).
        - Always ``upgrade head`` afterward so new revisions apply on boot.
        - If stamped at/ past a revision that adds columns create_all already
          created, migrations are idempotent (see schedule-fields revision).

        Failures are logged and swallowed so boot cannot die on migration.
        """
        try:
            from sqlalchemy import inspect as sa_inspect

            inspector = sa_inspect(engine)
            # Nothing to adopt yet — empty DB; upgrade head builds from scratch
            # only when an alembic path is used alone. App boot uses create_all.
            has_schema = inspector.has_table('games')
            has_alembic = inspector.has_table('alembic_version')

            from alembic import command
            from alembic.config import Config as AlembicConfig

            repo_root = os.path.dirname(PACKAGE_ROOT)
            ini_path = os.path.join(repo_root, 'alembic.ini')
            if not os.path.isfile(ini_path):
                _safe_print(
                    "[WARN] alembic.ini not found; skipping Alembic ensure"
                )
                return

            alembic_cfg = AlembicConfig(ini_path)

            if has_schema and not has_alembic:
                # Never stamp head here — that skips post-baseline DDL.
                command.stamp(alembic_cfg, self._ALEMBIC_BASELINE_REVISION)
                _safe_print(
                    "[OK] Stamped existing schema at Alembic baseline "
                    f"({self._ALEMBIC_BASELINE_REVISION})"
                )
            elif has_schema and has_alembic and inspector.has_table('scan_jobs'):
                # Repair installs that were stamped at head before schedule_*
                # landed: alembic thinks it is current but columns are missing.
                scan_cols = {
                    col['name'] for col in inspector.get_columns('scan_jobs')
                }
                if 'schedule_kind' not in scan_cols:
                    command.stamp(alembic_cfg, self._ALEMBIC_BASELINE_REVISION)
                    _safe_print(
                        "[OK] Re-stamped to Alembic baseline to apply "
                        "missing schedule columns"
                    )

            if has_schema or has_alembic:
                command.upgrade(alembic_cfg, 'head')
                _safe_print("[OK] Alembic upgrade head complete")
        except Exception as e:  # noqa: BLE001 - boot must not fail on this
            _safe_print(f"[WARN] Alembic ensure skipped: {e}")

    def _phase3_default_data(self):
        """Initialize all default data in the database."""
        _safe_print("Phase 3: Default data initialization")

        try:
            # Import config to get database URI
            from config import Config

            # Create engine and session for data operations
            engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)
            SessionLocal = sessionmaker(bind=engine)
            session = SessionLocal()

            try:
                # Initialize default data components
                self._init_default_settings(session)
                self._init_scanning_filters(session)
                self._init_allowed_file_types(session)
                self._init_discovery_sections(session)

                # Commit all changes
                session.commit()
                _safe_print("[OK] Default data initialization completed")
                return True

            except Exception as e:
                session.rollback()
                _safe_print(f"[ERR] Default data initialization failed: {e}")
                return False
            finally:
                session.close()
                engine.dispose()

        except Exception as e:
            _safe_print(f"[ERR] Phase 3 setup failed: {e}")
            return False

    def _phase4_filesystem(self):
        """Setup filesystem folders and theme files."""
        _safe_print("Phase 4: Filesystem setup")

        try:
            # Import config after environment is loaded
            from config import Config

            # Create required directories
            library_path = library_dir(PACKAGE_ROOT)
            themes_path = os.path.join(library_path, 'themes')
            images_path = os.path.join(library_path, 'images')
            zips_path = os.path.join(library_path, 'zips')

            # Get DEV_MODE with fallback for robustness
            try:
                dev_mode = Config.DEV_MODE
            except AttributeError:
                _safe_print("[WARN] Config.DEV_MODE not found, using environment fallback")
                dev_mode = os.getenv('DEV_MODE', 'false').lower() == 'true'

            # Handle theme installation
            self._setup_default_theme(themes_path, dev_mode)

            # Create other required directories
            for path, name in [(images_path, 'images'), (zips_path, 'zips')]:
                if not os.path.exists(path):
                    os.makedirs(path, exist_ok=True)
                    _safe_print(f"[OK] Created {name} directory")

            # Icon packs live on the library volume — ensure builtins exist every boot.
            try:
                installed = install_icon_themes(force=False, package_root=PACKAGE_ROOT)
                _safe_print(f"[OK] Icon packs ready: {', '.join(installed)}")
            except Exception as icon_err:
                _safe_print(f"[WARN] Icon pack install skipped: {icon_err}")

            # A library moved to a data folder (standalone) starts without the
            # art the install ships inside static/library.
            try:
                seeded = seed_shipped_library()
                if seeded:
                    _safe_print(f"[OK] Copied {seeded} shipped library file(s) into the data folder")
            except Exception as seed_err:
                _safe_print(f"[WARN] Shipped library files not copied: {seed_err}")

            # Theme fonts, same reasoning as the icon packs above: the runtime
            # directory is a volume, so a fresh one starts empty and has to be
            # repopulated from the tracked bundle. This used to happen only at
            # the end of first-run setup, and only over the network — an install
            # that was already past setup, or one behind a proxy, offered five
            # faces in the picker and had none of them on disk. A local copy
            # needs no network and no admin.
            try:
                from oneirodex.utils.font_install import seed_builtin_fonts

                fonts_path = os.path.join(library_path, 'fonts')
                seeded = seed_builtin_fonts(fonts_path)
                if seeded:
                    _safe_print(f"[OK] Theme fonts installed: {seeded} face(s)")
                else:
                    _safe_print("[OK] Theme fonts ready")
            except Exception as font_err:
                # Cosmetic: a missing face degrades to the next family in its
                # CSS stack, so this must never take a boot down.
                _safe_print(f"[WARN] Theme font install skipped: {font_err}")

            # The public demo must have its cores ready before the server starts
            # accepting clicks. Other installs provision their cores through
            # the normal setup flow or scripts/fetch-webretro-cores.sh.
            if os.getenv('ONEIRODEX_PUBLIC_DEMO', '').lower() == 'true':
                try:
                    from oneirodex.utils.webretro_core_install import install_missing_cores

                    demo_cores = ('nestopia', 'mgba', 'genesis_plus_gx', 'stella2014')
                    installed, failed = install_missing_cores(core_ids=demo_cores)
                    _safe_print(f"[OK] Public demo browser cores installed: {installed}")
                    if failed:
                        _safe_print(f"[WARN] Public demo browser cores unavailable: {', '.join(failed)}")
                except Exception as core_err:
                    _safe_print(f"[WARN] Public demo core install skipped: {core_err}")

            _safe_print("[OK] Filesystem setup completed")
            return True

        except Exception as e:
            _safe_print(f"[ERR] Filesystem setup failed: {e}")
            return False

    def _phase5_cleanup(self):
        """Cleanup operations and system event logging."""
        _safe_print("Phase 5: Cleanup and finalization")

        try:
            # Import config to get database URI
            from config import Config

            # Create engine and session for cleanup
            engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)
            SessionLocal = sessionmaker(bind=engine)
            session = SessionLocal()

            try:
                # Clean up orphaned scan jobs
                self._cleanup_orphaned_scan_jobs(session)

                # Log system startup event
                self._log_system_event(session)

                session.commit()
                _safe_print("[OK] Cleanup and finalization completed")
                return True

            except Exception as e:
                session.rollback()
                _safe_print(f"[ERR] Cleanup failed: {e}")
                return False
            finally:
                session.close()
                engine.dispose()

        except Exception as e:
            _safe_print(f"[ERR] Phase 5 failed: {e}")
            return False

    def _init_default_settings(self, session):
        """Initialize default global settings."""
        from oneirodex.models import GlobalSettings

        settings_record = session.execute(select(GlobalSettings)).scalars().first()
        if not settings_record:
            default_settings = {
                'showSystemLogo': True,
                'showHelpButton': True,
                'allowUsersToInviteOthers': True,
                'enableWebLinksOnDetailsPage': True,
                'enableServerStatusFeature': True,
                'enableNewsletterFeature': True,
                'showVersion': True
            }
            settings_record = GlobalSettings(settings=default_settings)
            session.add(settings_record)
            _safe_print("[OK] Created default global settings")
        else:
            _safe_print("Global settings already exist")

    def _init_scanning_filters(self, session):
        """Initialize default scanning filters."""
        from oneirodex.models import ReleaseGroup

        default_filters = [
            {'filter_pattern': 'Open Source', 'case_sensitive': 'no'},
            {'filter_pattern': 'Public Domain', 'case_sensitive': 'no'},
            {'filter_pattern': 'GOG', 'case_sensitive': 'no'},
        ]

        existing_groups = session.execute(select(ReleaseGroup.filter_pattern)).scalars().all()
        existing_group_names = set(existing_groups)

        added_count = 0
        for group in default_filters:
            if group['filter_pattern'] not in existing_group_names:
                new_group = ReleaseGroup(
                    filter_pattern=group['filter_pattern'],
                    case_sensitive=group['case_sensitive']
                )
                session.add(new_group)
                added_count += 1

        if added_count > 0:
            _safe_print(f"[OK] Added {added_count} default scanning filters")
        else:
            _safe_print("Scanning filters already exist")

    def _init_allowed_file_types(self, session):
        """Initialize default allowed file types."""
        # Circular: init_data imports InitManager at module load.
        from oneirodex.init_data import seeded_allowed_file_types
        from oneirodex.models import AllowedFileType

        existing_types = {ft.value for ft in session.execute(select(AllowedFileType)).scalars().all()}

        added_count = 0
        for file_type in seeded_allowed_file_types():
            if file_type not in existing_types:
                new_type = AllowedFileType(value=file_type)
                session.add(new_type)
                added_count += 1

        if added_count > 0:
            _safe_print(f"[OK] Added {added_count} default file types")
        else:
            _safe_print("File types already exist")

    def _init_discovery_sections(self, session):
        """Initialize default discovery sections."""
        from oneirodex.models import DiscoverySection

        default_sections = [
            {'name': 'Libraries', 'identifier': 'libraries', 'is_visible': True, 'display_order': 0},
            # 'Latest Games' is newest *released* (first_release_date); the shelf
            # below is newest *added here*. They were one shelf answering the
            # second question under the first question's name — see
            # routes_discover.build_discover_sections.
            {'name': 'Latest Games', 'identifier': 'latest_games', 'is_visible': True, 'display_order': 1},
            {'name': 'New Library Games', 'identifier': 'new_library_games', 'is_visible': True, 'display_order': 2},
            {'name': 'Most Downloaded', 'identifier': 'most_downloaded', 'is_visible': True, 'display_order': 3},
            {'name': 'Highest Rated', 'identifier': 'highest_rated', 'is_visible': True, 'display_order': 4},
            {'name': 'Last Updated', 'identifier': 'last_updated', 'is_visible': True, 'display_order': 5},
            {'name': 'Most Favorited', 'identifier': 'most_favorited', 'is_visible': True, 'display_order': 6},
            # Storefront shelves (W25-STORE-1) — derived, hidden when empty.
            {'name': 'Curated for you', 'identifier': 'curated_for_you', 'is_visible': True, 'display_order': 7},
            {'name': 'Upcoming', 'identifier': 'upcoming', 'is_visible': True, 'display_order': 8},
            # Personal rows lead: what you were doing, then what changed in your
            # library, then what everyone else likes. Charts are the least
            # informative rows for a member who already owns the library.
            #
            # Negative orders on purpose. The shelves above have carried 0-8
            # since the first install and an admin may have reordered them
            # since; seeding ahead of that range puts these first without
            # renumbering anyone's arrangement. The gaps leave room to drag
            # between.
            {'name': 'Continue Playing', 'identifier': 'continue_playing', 'is_visible': True, 'display_order': -40},
            {'name': 'Friends Are Playing', 'identifier': 'friends_playing', 'is_visible': True, 'display_order': -30},
            {'name': 'Recently Updated Files', 'identifier': 'game_updates', 'is_visible': True, 'display_order': -20},
            {'name': 'Extras not on the vault', 'identifier': 'extras_missing', 'is_visible': True, 'display_order': -15},
            {'name': 'News', 'identifier': 'news', 'is_visible': True, 'display_order': -10},
            {
                'name': 'Deep discounts',
                'identifier': 'store_deals',
                'is_visible': True,
                'display_order': -8,
            },
            # A template rather than a shelf: it renders nothing itself and
            # carries the visibility switch for the rows the recommender
            # generates. Hiding it turns the whole family off.
            {'name': 'Because You Played', 'identifier': 'because_you_played', 'is_visible': True, 'display_order': 9},
        ]

        existing_sections = {section.identifier for section in session.execute(select(DiscoverySection)).scalars().all()}

        added_count = 0
        for section in default_sections:
            if section['identifier'] not in existing_sections:
                new_section = DiscoverySection(
                    name=section['name'],
                    identifier=section['identifier'],
                    is_visible=section['is_visible'],
                    display_order=section['display_order']
                )
                session.add(new_section)
                added_count += 1

        if added_count > 0:
            _safe_print(f"[OK] Added {added_count} discovery sections")
        else:
            _safe_print("Discovery sections already exist")

    def _setup_default_theme(self, themes_path, dev_mode):
        """Install/refresh the default theme and the colour presets.

        The runtime themes folder is usually a Docker volume that outlives the
        image, so every boot reconciles it against the tracked source: any file
        whose content differs is rewritten, and presets generated from an older
        source snapshot are regenerated.
        """
        default_theme_target = os.path.join(themes_path, 'default')
        theme_json_path = os.path.join(default_theme_target, 'theme.json')
        theme_exists = os.path.exists(theme_json_path)
        default_theme_source = self.default_theme_source()

        if not os.path.exists(default_theme_source):
            _safe_print("[WARN] Theme source not found")
            return

        try:
            os.makedirs(themes_path, exist_ok=True)

            if not theme_exists or dev_mode:
                if dev_mode and os.path.exists(default_theme_target):
                    shutil.rmtree(default_theme_target)

                shutil.copytree(default_theme_source, default_theme_target, dirs_exist_ok=True)

                if dev_mode:
                    _safe_print("DEV_MODE: Theme files refreshed")
                else:
                    _safe_print("[OK] Default theme installed")
            else:
                synced = self._sync_theme_files(default_theme_source, default_theme_target)
                if synced:
                    _safe_print(f"[OK] Default theme updated ({synced} file(s) refreshed)")
                else:
                    _safe_print("Default theme already up to date")

            presets = install_preset_themes(themes_path, default_theme_source, force=bool(dev_mode))
            if presets:
                _safe_print(f"[OK] Rebuilt {presets} preset theme(s)")

            preset_files = sync_preset_themes(themes_path, default_theme_source)
            if preset_files:
                _safe_print(f"[OK] Refreshed {preset_files} preset theme file(s)")

            tokens_path = os.path.join(default_theme_target, 'css', 'od-tokens.css')
            if os.path.isfile(tokens_path):
                _safe_print(f"[OK] Theme tokens present: {tokens_path}")
            else:
                _safe_print(
                    "[ERR] Missing themes/default/css/od-tokens.css after sync — "
                    "UI theming will fall back incorrectly. Use Admin → Reset Default Themes."
                )
        except Exception as e:
            _safe_print(f"[ERR] Theme setup failed: {e}")

    @staticmethod
    def default_theme_source():
        """Absolute path to the tracked theme source inside the package."""
        return os.path.join(PACKAGE_ROOT, 'setup', 'default_theme')

    def _sync_theme_files(self, source_root, target_root):
        """Rewrite every target file whose content differs from the source.

        Supersedes the old fixed 'critical files' list: a changed stylesheet now
        propagates on the next boot no matter which file it is.
        """
        return sync_theme_tree(source_root, target_root)

    def _cleanup_orphaned_scan_jobs(self, session):
        """Clean up scan jobs left in 'Running' or 'Stopping' state after server restart."""
        from oneirodex.models import ScanJob
        from sqlalchemy import or_

        # Find jobs that were either running or in the process of stopping when server crashed
        orphaned_jobs = session.execute(
            select(ScanJob).filter(
                or_(ScanJob.status == 'Running', ScanJob.status == 'Stopping')
            )
        ).scalars().all()

        if orphaned_jobs:
            for job in orphaned_jobs:
                job.status = 'Failed'
                job.error_message = 'Scan job interrupted by server restart'
                job.is_enabled = False
                job.current_processing = None

            _safe_print(f"Cleaned up {len(orphaned_jobs)} orphaned scan jobs")
            # Queued jobs stay Queued; scan_scheduler drain promotes on next tick.
        else:
            _safe_print("No orphaned scan jobs found")

    def _log_system_event(self, session):
        """Log system startup event."""
        try:
            from oneirodex.models import SystemEvents
            from oneirodex import app_version

            event = SystemEvents(
                event_text=f"Oneirodex v{app_version} initialization completed",
                event_type='system',
                event_level='startup',
                audit_user=None
            )
            session.add(event)
            _safe_print("[OK] System startup event logged")
        except Exception as e:
            _safe_print(f"[WARN] Could not log system event: {e}")


def print_startup_epilogue(ready):
    """Close the launcher story before the web server begins its own logs."""
    from scripts.startup_art import print_startup_epilogue as print_art

    print_art(ready)

# Back-compat for init_data / older imports
InitManager = InitializationManager


# Global instance for easy access
_init_manager = None

def get_initialization_manager():
    """Get the global initialization manager instance."""
    global _init_manager
    if _init_manager is None:
        _init_manager = InitializationManager()
    return _init_manager


def run_complete_initialization():
    """Convenience function for running complete initialization."""
    manager = get_initialization_manager()
    return manager.run_complete_initialization()


def is_initialization_complete():
    """Check if initialization has been completed."""
    # First check environment variable (set after successful init)
    if os.getenv('ONEIRODEX_INITIALIZATION_COMPLETE') == 'true':
        return True

    # Check manager state if available
    if _init_manager is not None:
        return _init_manager._initialization_complete

    return False


def mark_initialization_complete():
    """Mark initialization as complete in environment."""
    os.environ['ONEIRODEX_INITIALIZATION_COMPLETE'] = 'true'
    os.environ['ONEIRODEX_MIGRATIONS_COMPLETE'] = 'true'


def run_complete_startup_initialization():
    """
    Run complete startup initialization and mark as complete.
    Entry point called from shell scripts before starting workers.
    """
    success = run_complete_initialization()
    if success:
        mark_initialization_complete()
    return success
