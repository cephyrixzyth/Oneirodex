import platform
import socket
import os
from datetime import datetime, timedelta, timezone
from sqlalchemy import func, select
from oneirodex.models import User, SystemEvents, GlobalSettings
from oneirodex import db
from oneirodex.utils.global_settings import global_settings_row
from config import Config
from urllib.parse import urlparse
from flask import current_app, has_app_context

def get_system_info():
    """Get basic system information."""
    try:
        hostname = socket.gethostname()
        ip_address = socket.gethostbyname(hostname)
    except Exception as e:
        hostname = 'Unavailable'
        ip_address = 'Unavailable'
        print(f"Error retrieving IP address: {e}")
    
    return {
        'Operating System': platform.system(),
        'Operating System Version': platform.version(),
        'Python Version': platform.python_version(),
        'Hostname': hostname,
        'IP Address': ip_address,
        'Current Time': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

# Ops rows for ONEIRODEX_LIBRARY_ROOTS entries are keyed with this prefix so the
# read-only-is-fine rule that already covers the games mount covers them too.
LIBRARY_ROOT_KEY_PREFIX = 'LIBRARY_ROOT: '


def _probe_path(path):
    """Existence / read / write for one configured path.

    Guarded because a severed network mount can raise from ``os.path.exists``
    rather than answering False, and that is precisely the case Ops exists to
    report.
    """
    try:
        exists = os.path.exists(path)
        return {
            'path': path,
            'read': os.access(path, os.R_OK) if exists else False,
            'write': os.access(path, os.W_OK) if exists else False,
            'exists': exists,
        }
    except OSError:
        return {'path': path, 'read': False, 'write': False, 'exists': False}


def get_config_values():
    """Get safe configuration values."""
    whitelist = {
        'BASE_FOLDER_WINDOWS': None,
        'BASE_FOLDER_POSIX': None,
        'DATA_FOLDER_GAMES': None,
        'IMAGE_SAVE_PATH': None,
        'UPLOAD_FOLDER': None
    }

    safe_config_values = {}
    # Ops runs against the live application configuration. Config is only the
    # class used to seed Flask at startup; create_app may relocate the library
    # directory or an install/test may override paths after that point.
    active_config = current_app.config if has_app_context() else None
    for item in whitelist:
        path = active_config.get(item) if active_config is not None else getattr(Config, item, None)
        if path:
            safe_config_values[item] = _probe_path(path)

    # Extra scan locations get their own rows so Ops shows a share that stopped
    # being mounted. An unmounted root is the failure that otherwise reads as
    # "the scan found nothing" with no explanation anywhere.
    # Keyed by label *and* path. Label alone collided: two roots sharing one —
    # `Archive=/mnt/a|Archive=/mnt/b` is a plausible typo — wrote the same dict
    # key, so one of them vanished from the very view that exists to report a
    # root that stopped being mounted.
    roots = active_config.get('LIBRARY_ROOTS') if active_config is not None else getattr(Config, 'LIBRARY_ROOTS', None)
    for root in roots or []:
        path = root.get('path')
        if not path:
            continue
        label = root.get('label') or path
        key = f'{LIBRARY_ROOT_KEY_PREFIX}{label}'
        if key in safe_config_values and safe_config_values[key].get('path') != path:
            key = f'{key} ({path})'
        safe_config_values[key] = _probe_path(path)

    return safe_config_values

def get_active_users():
    """Get count of users active in the last 24 hours."""
    return db.session.execute(select(func.count(User.id)).filter(
        User.lastlogin >= (datetime.now(timezone.utc) - timedelta(hours=24))
    )).scalar()

def get_log_info():
    """Get log statistics."""
    return {
        'count': db.session.execute(select(func.count(SystemEvents.id))).scalar(),
        'latest': db.session.execute(select(SystemEvents).order_by(SystemEvents.timestamp.desc())).scalars().first()
    }

def get_database_info():
    """Get database connection information."""
    try:
        # Get the current database URI
        db_uri = db.engine.url
        
        # Parse the database URI to extract components
        parsed = urlparse(str(db_uri))
        
        # Extract database name from path (remove leading slash)
        db_name = parsed.path.lstrip('/')
        
        # Get database host and port
        host = parsed.hostname or 'localhost'
        port = parsed.port or 5432
        
        # Get database engine type
        engine_type = db_uri.drivername
        
        return {
            'database_name': db_name,
            'host': host,
            'port': port,
            'engine': engine_type,
            'connection_info': f"{engine_type}://{host}:{port}/{db_name}"
        }
    except Exception as e:
        return {
            'database_name': 'Error retrieving database info',
            'host': 'Unknown',
            'port': 'Unknown', 
            'engine': 'Unknown',
            'connection_info': f'Error: {str(e)}'
        }

def check_server_settings():
    """Check if server settings are properly configured."""
    settings_record = global_settings_row()
    if not settings_record or not settings_record.settings:
        return False, "Server settings not configured."
    
    enable_server_status = settings_record.settings.get('enableServerStatusFeature', False)
    if not enable_server_status:
        return False, "Server Status feature is disabled."
    
    return True, None
