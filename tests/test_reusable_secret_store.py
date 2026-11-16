from __future__ import annotations

import json
import os
import importlib.util
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from alembic.migration import MigrationContext
from alembic.operations import Operations

from oneirodex.utils.secret_store import (
    decrypt_reusable_secret,
    encrypt_reusable_secret,
    has_global_secret,
    read_arr_settings,
    read_global_secret,
    read_reusable_secret,
    reusable_secret_storage_status,
    write_arr_settings,
    write_global_secret,
    migrate_reusable_secrets,
)
from oneirodex.utils.store_credentials import (
    StoreCredentialError,
    StoreCredentialKeyUnavailable,
    load_store_credential_keyring,
)
from oneirodex.models import GlobalSettings
from oneirodex.utils.igdb_settings import igdb_public_state
from oneirodex.utils.smtp_settings import smtp_public_state


def _keyring_file(tmp_path, *, active='current', keys=None):
    keys = keys or {'current': Fernet.generate_key().decode('ascii')}
    path = tmp_path / 'keyring.json'
    path.write_text(json.dumps({'active_key_id': active, 'keys': keys}), encoding='utf-8')
    if os.name != 'nt':
        path.chmod(0o600)
    return path


def test_reusable_secret_is_encrypted_and_bound_to_its_context(tmp_path):
    keyring_path = _keyring_file(tmp_path)
    ring = load_store_credential_keyring(str(keyring_path))
    canary = 'not-for-database-or-logs-7e7f11'

    envelope = encrypt_reusable_secret(
        canary, context='global_settings.smtp_password', keyring=ring,
    )

    assert envelope.startswith('odrc:v1:current:')
    assert canary not in envelope
    assert keyring_path.read_text(encoding='utf-8').split('"current": "')[1].split('"')[0] not in repr(ring)
    assert decrypt_reusable_secret(
        envelope, context='global_settings.smtp_password', keyring=ring,
    ) == canary
    with pytest.raises(StoreCredentialError, match='context') as caught:
        decrypt_reusable_secret(
            envelope, context='global_settings.oidc_client_secret', keyring=ring,
        )
    assert canary not in str(caught.value)


def test_indexer_context_is_bounded_and_distinct_for_long_ids():
    from oneirodex.utils.secret_store import arr_secret_context

    long_context = arr_secret_context('api_key', indexer_id='x' * 128)
    other_context = arr_secret_context('api_key', indexer_id='y' * 128)
    assert len(long_context) <= 192
    assert long_context != other_context
    assert 'x' * 128 not in long_context


def test_reusable_secret_rejects_tamper_unknown_key_and_unknown_version(tmp_path):
    ring = load_store_credential_keyring(str(_keyring_file(tmp_path)))
    envelope = encrypt_reusable_secret(
        'secret-canary', context='global_settings.smtp_password', keyring=ring,
    )
    tampered = envelope[:-2] + ('AA' if envelope[-2:] != 'AA' else 'BB')

    with pytest.raises(StoreCredentialError):
        decrypt_reusable_secret(
            tampered, context='global_settings.smtp_password', keyring=ring,
        )
    with pytest.raises(StoreCredentialKeyUnavailable):
        decrypt_reusable_secret(
            envelope.replace(':current:', ':retired:'),
            context='global_settings.smtp_password', keyring=ring,
        )
    with pytest.raises(StoreCredentialError):
        read_reusable_secret(
            'odrc:v2:unknown-format', context='global_settings.smtp_password',
            keyring=ring,
        )

    wrong_ring = load_store_credential_keyring(str(_keyring_file(
        tmp_path, active='current', keys={'current': Fernet.generate_key().decode('ascii')},
    )))
    with pytest.raises(StoreCredentialError):
        decrypt_reusable_secret(
            envelope, context='global_settings.smtp_password', keyring=wrong_ring,
        )


def test_missing_key_does_not_fall_back_to_ciphertext_or_plaintext(tmp_path, monkeypatch):
    first = load_store_credential_keyring(str(_keyring_file(tmp_path)))
    envelope = encrypt_reusable_secret(
        'unavailable-canary', context='global_settings.smtp_password', keyring=first,
    )
    missing_ring = _keyring_file(
        tmp_path, active='other', keys={'other': Fernet.generate_key().decode('ascii')},
    )
    monkeypatch.setenv('ONEIRODEX_REUSABLE_SECRET_KEYRING_FILE', str(missing_ring))

    with pytest.raises(StoreCredentialKeyUnavailable):
        read_reusable_secret(envelope, context='global_settings.smtp_password')
    assert 'unavailable-canary' not in envelope
    assert envelope.startswith('odrc:v1:')


def test_missing_key_status_is_actionable_and_redacts_paths(monkeypatch):
    monkeypatch.delenv('ONEIRODEX_REUSABLE_SECRET_KEYRING_FILE', raising=False)
    monkeypatch.delenv('ONEIRODEX_STORE_CREDENTIAL_KEYRING_FILE', raising=False)

    state = reusable_secret_storage_status()

    assert state['available'] is False
    assert 'Restore the operator-managed key-ring backup' in state['message']
    assert 'reconnect affected integrations' in state['message']
    assert 'C:\\' not in state['message']


def test_global_setting_writer_encrypts_blank_clears_and_presence_is_safe(tmp_path, monkeypatch):
    path = _keyring_file(tmp_path)
    monkeypatch.setenv('ONEIRODEX_REUSABLE_SECRET_KEYRING_FILE', str(path))
    row = SimpleNamespace(smtp_password=None)
    canary = 'smtp-secret-canary'

    write_global_secret(row, 'smtp_password', canary)

    assert row.smtp_password.startswith('odrc:v1:')
    assert canary not in row.smtp_password
    assert has_global_secret(row, 'smtp_password')
    assert read_global_secret(row, 'smtp_password') == canary
    write_global_secret(row, 'smtp_password', '')
    assert row.smtp_password is None
    assert not has_global_secret(row, 'smtp_password')


def test_secret_public_projections_never_serialize_secret_values(tmp_path, monkeypatch):
    monkeypatch.setenv(
        'ONEIRODEX_REUSABLE_SECRET_KEYRING_FILE', str(_keyring_file(tmp_path)),
    )
    canary = 'projection-secret-canary'
    row = SimpleNamespace(
        smtp_password=None, igdb_client_secret=None, igdb_client_id='client-id',
        smtp_enabled=True, smtp_server='smtp.example.test', smtp_port=587,
        smtp_username='mailer', smtp_use_tls=True, smtp_default_sender='a@example.test',
        smtp_last_tested=None, igdb_last_tested=None,
    )
    write_global_secret(row, 'smtp_password', canary)
    write_global_secret(row, 'igdb_client_secret', canary)

    projections = [smtp_public_state(row), igdb_public_state(row)]
    serialized = json.dumps(projections)
    assert canary not in serialized
    assert all('odrc:' not in json.dumps(projection) for projection in projections)
    assert projections[0]['password_saved'] is True
    assert projections[1]['secret_present'] is True


def test_arr_secret_values_round_trip_without_changing_nonsecret_settings(tmp_path, monkeypatch):
    from oneirodex.utils.secret_store import ARR_SECRET_FIELDS

    monkeypatch.setenv(
        'ONEIRODEX_REUSABLE_SECRET_KEYRING_FILE', str(_keyring_file(tmp_path)),
    )
    row = SimpleNamespace(arr_settings=None)
    values = {field: f'{field}-canary' for field in ARR_SECRET_FIELDS}
    values.update({
        'prowlarr_url': 'https://indexer.example.test',
        'indexers': [{
            'id': 'indexer-01', 'name': 'Fixture', 'url': 'https://indexer.test',
            'api_key': 'indexer-secret-canary',
        }],
    })

    write_arr_settings(row, values)

    stored = json.dumps(row.arr_settings)
    for field in ARR_SECRET_FIELDS:
        assert values[field] not in stored
    assert 'indexer-secret-canary' not in stored
    restored = read_arr_settings(row)
    assert restored == values


def test_reusable_migration_is_verified_restartable_and_rotates_keys(tmp_path, monkeypatch):
    first_key = Fernet.generate_key().decode('ascii')
    second_key = Fernet.generate_key().decode('ascii')
    path = _keyring_file(tmp_path, active='first', keys={'first': first_key})
    backup_path = tmp_path / 'operator-backup' / 'keyring.json'
    backup_path.parent.mkdir()
    backup_path.write_bytes(path.read_bytes())
    monkeypatch.setenv('ONEIRODEX_REUSABLE_SECRET_KEYRING_FILE', str(path))
    engine = create_engine('sqlite://')
    GlobalSettings.__table__.create(engine)
    scalar_canary = 'legacy-smtp-canary'
    arr_canary = 'legacy-indexer-canary'
    with Session(engine) as session:
        session.add(GlobalSettings(
            smtp_password=scalar_canary,
            arr_settings={
                'prowlarr_api_key': 'legacy-prowlarr-canary',
                'indexers': [{'id': 'idx-1', 'api_key': arr_canary}],
            },
        ))
        session.commit()

        first = migrate_reusable_secrets(session)
        stored = session.get(GlobalSettings, 1)
        first_ciphertext = stored.smtp_password
        first_indexer_ciphertext = stored.arr_settings['indexers'][0]['api_key']
        assert first['secrets_encrypted'] == 3
        assert first['remaining_legacy'] == 0
        assert scalar_canary not in first_ciphertext
        assert arr_canary not in first_indexer_ciphertext

        rerun = migrate_reusable_secrets(session)
        assert rerun['secrets_encrypted'] == 0
        assert rerun['secrets_rotated'] == 0
        assert session.get(GlobalSettings, 1).smtp_password == first_ciphertext

        path.write_text(json.dumps({
            'active_key_id': 'second', 'keys': {'second': second_key},
        }), encoding='utf-8')
        unavailable = migrate_reusable_secrets(session)
        assert unavailable['failures'] == 1
        assert session.get(GlobalSettings, 1).smtp_password == first_ciphertext

        # Recover the matching key from the separately stored operator backup.
        # The database ciphertext remains untouched while its key is absent.
        path.write_bytes(backup_path.read_bytes())
        recovered = session.get(GlobalSettings, 1)
        assert read_global_secret(recovered, 'smtp_password') == scalar_canary
        assert read_arr_settings(recovered)['indexers'][0]['api_key'] == arr_canary

        path.write_text(json.dumps({
            'active_key_id': 'second', 'keys': {'first': first_key, 'second': second_key},
        }), encoding='utf-8')
        rotated = migrate_reusable_secrets(session)
        row = session.get(GlobalSettings, 1)
        assert rotated['secrets_rotated'] == 3
        assert row.smtp_password.startswith('odrc:v1:second:')
        assert row.arr_settings['indexers'][0]['api_key'].startswith('odrc:v1:second:')
        assert read_global_secret(row, 'smtp_password') == scalar_canary
        assert read_arr_settings(row)['indexers'][0]['api_key'] == arr_canary
    engine.dispose()


def test_reusable_secret_alembic_revision_widens_existing_scalar_columns():
    revision_path = os.path.join(
        os.path.dirname(__file__), '..', 'alembic', 'versions',
        'c1d2e3f4a5b6_store_reusable_secret_envelopes.py',
    )
    spec = importlib.util.spec_from_file_location('reusable_secret_revision', revision_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine('sqlite://')
    GlobalSettings.__table__.create(engine)
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
        columns = {column['name']: column['type'] for column in __import__('sqlalchemy').inspect(connection).get_columns('global_settings')}
    assert all('TEXT' in str(columns[name]).upper() for name in (
        'smtp_password', 'igdb_client_secret', 'oidc_client_secret',
        'steam_web_api_key', 'steamgriddb_api_key', 'giantbomb_api_key',
        'mobygames_api_key', 'thegamesdb_api_key', 'retroachievements_api_key',
    ))
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            module.downgrade()
        columns = {column['name']: column['type'] for column in __import__('sqlalchemy').inspect(connection).get_columns('global_settings')}
    assert {name: columns[name].length for name in module._LEGACY_LENGTHS} == module._LEGACY_LENGTHS
    engine.dispose()
