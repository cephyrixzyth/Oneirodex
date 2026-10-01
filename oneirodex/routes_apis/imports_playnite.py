"""Playnite library import API (register-only ownership marks)."""

from flask import request
from flask_login import current_user, login_required

from oneirodex.utils.api_response import api_error, api_ok
from oneirodex.utils.playnite_import import import_playnite_csv, import_playnite_json
from oneirodex.utils.store_ownership_common import is_ownership_sync_enabled

from . import apis_bp


@apis_bp.route('/imports/playnite', methods=['POST'])
@login_required
def import_playnite():
    """
    Import a Playnite library export.

    JSON body: raw Playnite export object/list, or multipart file (.json/.csv).
    Creates store='playnite' ownership rows and matches local games by name.
    Never downloads or installs from stores.
    """
    # The provider registry reports Playnite as disabled when the administrator
    # turns store ownership off; the import has to agree with it.
    if not is_ownership_sync_enabled():
        return api_error('Store ownership sync is disabled by administrator', code='forbidden')
    upload = request.files.get('file')
    try:
        if upload:
            filename = (upload.filename or '').lower()
            raw = upload.read()
            try:
                text = raw.decode('utf-8-sig')
            except UnicodeDecodeError:
                return api_error('File must be UTF-8 text', code='bad_request')
            if filename.endswith('.csv'):
                result = import_playnite_csv(current_user.id, text)
            else:
                result = import_playnite_json(current_user.id, text)
        else:
            data = request.get_json(silent=True)
            if data is None:
                return api_error('JSON body or file upload required', code='bad_request')
            result = import_playnite_json(current_user.id, data)
    except ValueError:
        # json.JSONDecodeError and malformed rows: say so rather than a logged 500.
        return api_error('The Playnite export could not be read', code='bad_request')

    if result.errors and result.imported == 0 and result.matched == 0:
        # The importer's own fixed sentence ("CSV must include a Name column"),
        # with the counts kept at the top level where callers read them.
        return api_error(result.errors[0], code='bad_request', **result.to_dict())
    return api_ok(result.to_dict())
