"""Keep account-deletion policy aligned with ORM and database user references."""

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import Enum, JSON, and_, inspect, insert, select
from sqlalchemy.sql.sqltypes import Boolean, DateTime, Float, Integer, String


EXPECTED_USER_FKS = {
    'announcements.author_user_id': 'SET NULL',
    'api_tokens.user_id': 'CASCADE',
    'chat_spaces.created_by_user_id': 'SET NULL',
    'client_devices.user_id': 'CASCADE',
    'custom_emoji.uploaded_by_user_id': 'SET NULL',
    'detail_layout_presets.user_id': 'CASCADE',
    'duplicate_fix_logs.actor_user_id': None,
    'game_collections.owner_user_id': 'SET NULL',
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


def test_deletion_manifest_matches_user_foreign_key_inventory(db_session):
    manifest_path = (
        Path(__file__).resolve().parents[1]
        / 'docs' / 'dev' / 'parity-evidence'
        / 'account-deletion-relation-manifest-r1994.json'
    )
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    relations = {item['foreign_key']: item for item in manifest['relations']}
    assert set(relations) == set(EXPECTED_USER_FKS)
    assert len(relations) == 50
    assert {
        key: (None if value['on_delete'] == 'NO ACTION' else value['on_delete'])
        for key, value in relations.items()
    } == EXPECTED_USER_FKS
    assert all(item['disposition'] and item['policy'] for item in relations.values())
    assert all(
        item['synthetic_fixture'] in {
            'covered', 'inventory_only', 'public_retention_and_private_deletion_covered',
        }
        for item in relations.values()
    )
    assert _database_user_fk_actions(db_session.connection()) == EXPECTED_USER_FKS
    assert all(
        item['disposition'] == NO_ACTION_DISPOSITIONS[key]
        for key, item in relations.items()
        if EXPECTED_USER_FKS[key] is None
    )


def _fixture_column_value(column, table_name, suffix):
    column_type = column.type
    if isinstance(column_type, Enum):
        if column_type.enum_class is not None:
            return next(iter(column_type.enum_class))
        return column_type.enums[0]
    if isinstance(column_type, Boolean):
        return False
    if isinstance(column_type, DateTime):
        return datetime.now(timezone.utc)
    if isinstance(column_type, Integer):
        return 1
    if isinstance(column_type, Float):
        return 1.0
    if isinstance(column_type, JSON) or column_type.__class__.__name__ == 'JSONEncodedDict':
        return {}
    if isinstance(column_type, String):
        value = f'fx-{suffix}-{table_name}-{column.name}'
        return value[:column_type.length] if column_type.length else value
    raise AssertionError(
        f'No account-deletion fixture value for {table_name}.{column.name} '
        f'({column_type!r})'
    )


def test_populated_manifest_relations_follow_owner_dispositions(db_session, tmp_path, monkeypatch):
    from oneirodex.models import (
        ChatChannel,
        ChatMessage,
        ChatSpace,
        Game,
        Library,
        ScanJob,
        User,
        UserOwnedTitle,
        db,
    )
    from oneirodex.platform import LibraryPlatform
    from oneirodex.utils import user_deletion
    from oneirodex.utils.user_deletion import delete_user_account

    manifest_path = (
        Path(__file__).resolve().parents[1]
        / 'docs' / 'dev' / 'parity-evidence'
        / 'account-deletion-relation-manifest-r1994.json'
    )
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    suffix = uuid4().hex[:10]
    upload_root = tmp_path / 'uploads'
    save_root = tmp_path / 'saves'
    save_root.mkdir()
    monkeypatch.setattr(
        user_deletion, '_storage_roots', lambda: (upload_root.resolve(), save_root.resolve()),
    )

    def make_user(name, role):
        user = User(
            name=f'{name}_{suffix}',
            email=f'{name}_{suffix}@example.test',
            user_id=str(uuid4()),
            role=role,
            state=True,
            is_email_verified=True,
        )
        user.set_password('synthetic account-deletion fixture password')
        return user

    # Exercise the same ownership cleanup for a child account; relation
    # disposition must not depend on role.
    departing = make_user('manifest_departing', 'child')
    survivor = make_user('manifest_survivor', 'admin')
    db_session.add_all([departing, survivor])
    db_session.flush()

    library = Library(
        name=f'Deletion fixture {suffix}',
        platform=LibraryPlatform.NES,
        display_order=0,
    )
    db_session.add(library)
    db_session.flush()
    game = Game(
        uuid=str(uuid4()),
        name=f'Deletion fixture game {suffix}',
        library_uuid=library.uuid,
        full_disk_path=f'/synthetic/deletion-fixture/{suffix}.nes',
    )
    space = ChatSpace(
        name=f'Deletion fixture space {suffix}',
        created_by_user_id=survivor.id,
    )
    db_session.add_all([game, space])
    db_session.flush()
    channel = ChatChannel(
        name=f'Deletion fixture channel {suffix}',
        space_id=space.id,
        created_by_user_id=survivor.id,
    )
    db_session.add(channel)
    db_session.flush()
    message = ChatMessage(
        channel_id=channel.id,
        user_id=survivor.id,
        body=f'Deletion fixture parent message {suffix}',
    )
    scan_job = ScanJob(
        folders=[],
        content_type='Games',
        schedule='24_hours',
        status='Completed',
        library_uuid=library.uuid,
    )
    parent_title = UserOwnedTitle(
        user_id=survivor.id,
        store='steam',
        external_app_id=f'parent-{suffix}',
    )
    db_session.add_all([message, scan_job, parent_title])
    db_session.flush()

    user_refs = {
        'users.id': (departing.id, survivor.id),
        'users.user_id': (departing.user_id, survivor.user_id),
    }
    parent_refs = {
        'games.uuid': game.uuid,
        'libraries.uuid': library.uuid,
        'chat_spaces.id': space.id,
        'chat_channels.id': channel.id,
        'chat_messages.id': message.id,
        'scan_jobs.id': scan_job.id,
        'user_owned_titles.id': parent_title.id,
    }
    relations = manifest['relations']
    assert len(relations) == 50
    populated = []
    metadata = db.Model.metadata
    for relation in relations:
        table_name, target_column_name = relation['foreign_key'].split('.', 1)
        table = metadata.tables[table_name]
        values = {}
        for column in table.columns:
            target = next((fk.target_fullname for fk in column.foreign_keys), None)
            if target in user_refs:
                departing_value, survivor_value = user_refs[target]
                values[column.name] = (
                    departing_value if column.name == target_column_name else survivor_value
                )
            elif target in parent_refs:
                values[column.name] = parent_refs[target]
            elif table_name == 'game_collections' and column.name == 'is_public':
                values[column.name] = True
            elif table_name == 'game_collections' and column.name == 'is_system':
                values[column.name] = False
            elif table_name == 'emulator_saves' and column.name == 'storage_path':
                save_path = save_root / f'fixture-save-{suffix}.state'
                save_path.write_bytes(b'synthetic save')
                values[column.name] = str(save_path)
            elif (
                column.default is not None
                or column.server_default is not None
                or column.identity is not None
                or (
                    column.primary_key
                    and isinstance(column.type, Integer)
                    and column.autoincrement in (True, 'auto')
                )
            ):
                continue
            elif column.nullable:
                continue
            else:
                values[column.name] = _fixture_column_value(
                    column, table_name, f'{suffix}-{target_column_name}',
                )

        primary_key = tuple(table.primary_key.columns)
        inserted = db_session.execute(
            insert(table).values(**values).returning(*primary_key)
        ).one()
        populated.append((
            table,
            target_column_name,
            relation['disposition'],
            primary_key,
            tuple(inserted),
        ))

    db_session.flush()
    collection_relation = next(
        item for item in populated if item[0].name == 'game_collections'
    )
    collection_table, _column_name, _disposition, collection_pk, collection_values = collection_relation
    collection_predicate = and_(
        *(column == value for column, value in zip(collection_pk, collection_values))
    )
    public_collection_id = db_session.execute(
        select(collection_table.c.id).where(collection_predicate)
    ).scalar_one()
    from oneirodex.models import GameCollectionItem

    private_collection = db_session.execute(
        insert(collection_table).values(
            uuid=str(uuid4()),
            name=f'Private deletion fixture {suffix}',
            description='private text owned by departing user',
            owner_user_id=departing.id,
            is_public=False,
            is_system=False,
            created_at=datetime.now(timezone.utc),
        ).returning(collection_table.c.id)
    ).scalar_one()
    db_session.add_all([
        GameCollectionItem(collection_id=public_collection_id, game_uuid=game.uuid, position=0),
        GameCollectionItem(collection_id=private_collection, game_uuid=game.uuid, position=0),
    ])
    db_session.flush()
    private_collection_item = db_session.execute(
        select(GameCollectionItem.id).where(
            GameCollectionItem.collection_id == private_collection,
        )
    ).scalar_one()
    assert len(populated) == len(EXPECTED_USER_FKS)
    assert all(
        item['synthetic_fixture'] in {
            'covered', 'public_retention_and_private_deletion_covered',
        }
        for item in relations
    )
    assert all(
        item['synthetic_fixture'] == 'covered'
        for item in manifest['managed_files']
    )

    delete_user_account(db_session, departing)
    db_session.expire_all()

    for table, target_column_name, disposition, primary_key, primary_key_values in populated:
        predicate = and_(*(
            column == value for column, value in zip(primary_key, primary_key_values)
        ))
        row = db_session.execute(select(table).where(predicate)).mappings().first()
        if disposition in {
            'retain_shared_row_clear_user_reference',
            'retain_public_collection_delete_private',
        }:
            assert row is not None, f'{table.name}.{target_column_name} shared row was deleted'
            assert row[target_column_name] is None
        elif disposition in {
            'clear_actor_reference', 'clear_reference', 'anonymize_and_retain_audit',
        }:
            assert row is not None, f'{table.name}.{target_column_name} retained row was deleted'
            assert row[target_column_name] is None
        else:
            assert row is None, f'{table.name}.{target_column_name} row survived deletion'

    assert db_session.get(User, survivor.id) is not None
    assert db_session.execute(
        select(collection_table.c.owner_user_id).where(collection_predicate)
    ).scalar_one_or_none() is None
    assert db_session.execute(
        select(collection_table.c.id).where(collection_table.c.id == private_collection)
    ).first() is None
    assert db_session.execute(
        select(GameCollectionItem.id).where(
            GameCollectionItem.collection_id == public_collection_id,
        )
    ).first() is not None
    assert db_session.get(GameCollectionItem, private_collection_item) is None
