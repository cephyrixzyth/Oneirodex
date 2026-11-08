"""Keep account-deletion policy aligned with ORM and database user references."""

from sqlalchemy import inspect


EXPECTED_USER_FKS = {
    'announcements.author_user_id': 'SET NULL',
    'api_tokens.user_id': 'CASCADE',
    'chat_spaces.created_by_user_id': 'SET NULL',
    'client_devices.user_id': 'CASCADE',
    'custom_emoji.uploaded_by_user_id': 'SET NULL',
    'detail_layout_presets.user_id': 'CASCADE',
    'duplicate_fix_logs.actor_user_id': None,
    'game_collections.owner_user_id': 'CASCADE',
    'invite_tokens.creator_user_id': None,
    'invite_tokens.used_by': None,
    'newsletters.sender_id': None,
    'persistent_login_sessions.user_id': 'CASCADE',
    'reference_sets.uploaded_by_user_id': 'SET NULL',
    'saved_filters.user_id': 'CASCADE',
    'store_accounts.user_id': 'CASCADE',
    'store_sync_jobs.user_id': 'CASCADE',
    'store_sync_jobs.actor_id': 'SET NULL',
    'support_tickets.user_id': 'CASCADE',
    'support_tickets.resolved_by_user_id': 'SET NULL',
    'system_events.audit_user': None,
    'user_attract_mode_settings.user_id': None,
    'user_content_filters.user_id': 'CASCADE',
    'user_friendships.user_id': 'CASCADE',
    'user_friendships.friend_user_id': 'CASCADE',
    'user_library_access.user_id': 'CASCADE',
    'user_notifications.user_id': 'CASCADE',
    'user_notifications.actor_user_id': 'SET NULL',
    'user_preferences.user_id': 'CASCADE',
    'user_taste_facets.user_id': 'CASCADE',
    'chat_channels.created_by_user_id': 'SET NULL',
    'chat_space_invites.created_by_user_id': 'SET NULL',
    'chat_space_members.user_id': 'CASCADE',
    'download_requests.user_id': None,
    'emulator_saves.user_id': 'CASCADE',
    'game_related_media.created_by_user_id': 'SET NULL',
    'game_requests.user_id': 'CASCADE',
    'game_requests.resolved_by_user_id': 'SET NULL',
    'pc_cheats.created_by_user_id': 'SET NULL',
    'play_sessions.user_id': 'CASCADE',
    'unmatched_folders.bad_match_by_user_id': 'SET NULL',
    'user_discover_impressions.user_id': 'CASCADE',
    'user_favorites.user_id': None,
    'user_game_progress.user_id': 'CASCADE',
    'user_game_status.user_id': None,
    'user_owned_titles.user_id': 'CASCADE',
    'chat_channel_members.user_id': 'CASCADE',
    'chat_messages.user_id': 'SET NULL',
    'ownership_match_decisions.actor_id': 'CASCADE',
    'chat_message_attachments.uploaded_by_user_id': 'CASCADE',
    'chat_message_reactions.user_id': 'CASCADE',
}

NO_ACTION_DISPOSITIONS = {
    'duplicate_fix_logs.actor_user_id': 'clear_actor_reference',
    'invite_tokens.creator_user_id': 'delete_owned_invites',
    'invite_tokens.used_by': 'clear_reference',
    'newsletters.sender_id': 'delete_authored_newsletters',
    'system_events.audit_user': 'anonymize_and_retain_audit',
    'user_attract_mode_settings.user_id': 'delete_personal_settings',
    'download_requests.user_id': 'delete_user_requests',
    'user_favorites.user_id': 'delete_user_associations',
    'user_game_status.user_id': 'delete_user_associations',
}


def _orm_user_fk_actions(metadata):
    result = {}
    for table in metadata.tables.values():
        for column in table.columns:
            for fk in column.foreign_keys:
                if fk.target_fullname in {'users.id', 'users.user_id'}:
                    result[f'{table.name}.{column.name}'] = fk.ondelete
    return result


def _database_user_fk_actions(connection):
    inspector = inspect(connection)
    result = {}
    for table_name in inspector.get_table_names():
        for foreign_key in inspector.get_foreign_keys(table_name):
            if foreign_key.get('referred_table') != 'users':
                continue
            for column_name in foreign_key.get('constrained_columns') or ():
                result[f'{table_name}.{column_name}'] = foreign_key.get('options', {}).get('ondelete')
    return result


def test_user_fk_inventory_and_no_action_dispositions_match_database(db_session):
    from oneirodex.models import db

    orm_actions = _orm_user_fk_actions(db.Model.metadata)
    assert len(orm_actions) == 50
    assert orm_actions == EXPECTED_USER_FKS
    assert _database_user_fk_actions(db_session.connection()) == EXPECTED_USER_FKS
    no_action = {key for key, action in EXPECTED_USER_FKS.items() if action is None}
    assert no_action == set(NO_ACTION_DISPOSITIONS)
