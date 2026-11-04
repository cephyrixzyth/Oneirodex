"""Store-provider credentials are encrypted independently of application sessions."""
from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from scripts.migrate_store_credentials import resolve_database_url

from oneirodex.utils.store_credentials import (
    StoreCredentialError,
    StoreCredentialKeyUnavailable,
    StoreCredentialMigrationRequired,
    decrypt_store_credential,
    encrypt_store_credential,
    load_store_credential_keyring,
    read_store_credential,
    write_store_credential,
)


def keyring_file(tmp_path, *, active='current', keys=None):
    keys = keys or {'current': Fernet.generate_key().decode('ascii')}
    path = tmp_path / 'keyring.json'
    path.write_text(json.dumps({'active_key_id': active, 'keys': keys}), encoding='utf-8')
    if os.name != 'nt':
        path.chmod(0o600)
    return path


def test_store_credentials_round_trip_and_ciphertext_hides_plaintext(tmp_path):
    path = keyring_file(tmp_path)
    ring = load_store_credential_keyring(str(path))

    ciphertext = encrypt_store_credential('provider-refresh-secret', keyring=ring)

    assert ciphertext.startswith('odsc:v1:current:')
    assert 'provider-refresh-secret' not in ciphertext
    assert decrypt_store_credential(ciphertext, keyring=ring) == 'provider-refresh-secret'


def test_store_credentials_rotate_using_decrypt_only_key(tmp_path):
    old_key = Fernet.generate_key().decode('ascii')
    active_key = Fernet.generate_key().decode('ascii')
    ring = load_store_credential_keyring(
        str(keyring_file(tmp_path, active='new', keys={'old': old_key, 'new': active_key}))
    )
    old_ring = load_store_credential_keyring(
        str(keyring_file(tmp_path, active='old', keys={'old': old_key}))
    )
    prior = encrypt_store_credential('provider-secret', keyring=old_ring)

    rotated = encrypt_store_credential(decrypt_store_credential(prior, keyring=ring), keyring=ring)

    assert rotated.startswith('odsc:v1:new:')
    assert decrypt_store_credential(rotated, keyring=ring) == 'provider-secret'


def test_store_credential_rejects_tampering_and_unknown_key_id(tmp_path):
    ring = load_store_credential_keyring(str(keyring_file(tmp_path)))
    ciphertext = encrypt_store_credential('provider-secret', keyring=ring)
    tampered = ciphertext[:-2] + ('AA' if ciphertext[-2:] != 'AA' else 'BB')

    with pytest.raises(StoreCredentialError):
        decrypt_store_credential(tampered, keyring=ring)
    with pytest.raises(StoreCredentialKeyUnavailable):
        decrypt_store_credential(ciphertext.replace('current', 'retired'), keyring=ring)


def test_missing_or_invalid_keyring_fails_closed(tmp_path):
    with pytest.raises(StoreCredentialKeyUnavailable):
        load_store_credential_keyring(str(tmp_path / 'missing.json'))

    invalid = tmp_path / 'invalid.json'
    invalid.write_text('{"active_key_id":"bad","keys":{"bad":"not-a-fernet-key"}}', encoding='utf-8')
    if os.name != 'nt':
        invalid.chmod(0o600)
    with pytest.raises(StoreCredentialKeyUnavailable):
        load_store_credential_keyring(str(invalid))


def test_keyring_rejects_group_or_world_readable_file(tmp_path):
    if os.name == 'nt':
        pytest.skip('Windows ACLs are not represented by POSIX mode bits')
    path = keyring_file(tmp_path)
    path.chmod(0o644)

    with pytest.raises(StoreCredentialKeyUnavailable, match='permissions'):
        load_store_credential_keyring(str(path))


def test_store_account_reader_never_falls_back_to_legacy_plaintext(tmp_path):
    ring = load_store_credential_keyring(str(keyring_file(tmp_path)))
    account = SimpleNamespace(credential='legacy-plaintext', credential_ciphertext=None)

    with pytest.raises(StoreCredentialMigrationRequired):
        read_store_credential(account)

    account.credential_ciphertext = 'odsc:v1:missing:token'
    with pytest.raises(StoreCredentialKeyUnavailable):
        read_store_credential(account)


def test_store_account_writer_encrypts_and_clears_plaintext(tmp_path, monkeypatch):
    path = keyring_file(tmp_path)
    monkeypatch.setenv('ONEIRODEX_STORE_CREDENTIAL_KEYRING_FILE', str(path))
    account = SimpleNamespace(credential='old-value', credential_ciphertext=None)

    write_store_credential(account, 'new-value')

    assert account.credential is None
    assert account.credential_ciphertext
    assert read_store_credential(account) == 'new-value'


def make_embedded_config(config_dir, password='never-print-this-password'):
    pgdata = config_dir / 'pgdata'
    secrets = config_dir / 'secrets'
    pgdata.mkdir(parents=True)
    secrets.mkdir()
    (pgdata / 'PG_VERSION').write_text('17\n', encoding='ascii')
    password_file = secrets / 'db_password'
    password_file.write_text(password + '\n', encoding='ascii')
    if os.name != 'nt':
        secrets.chmod(0o700)
        password_file.chmod(0o600)
    return password


def test_embedded_database_url_matches_single_container_defaults(tmp_path):
    from sqlalchemy.engine import URL

    password = make_embedded_config(tmp_path)
    url = resolve_database_url({
        'ONEIRODEX_EMBEDDED_DB': 'true',
        'ONEIRODEX_CONFIG_DIR': str(tmp_path),
    })

    assert isinstance(url, URL)
    assert url.drivername == 'postgresql'
    assert url.username == 'oneirodex'
    assert url.password == password
    assert url.host == '127.0.0.1'
    assert url.port == 55432
    assert url.database == 'oneirodex'


def test_auto_and_explicit_external_database_resolution(tmp_path):
    from sqlalchemy.engine import URL

    make_embedded_config(tmp_path)
    embedded = resolve_database_url({'ONEIRODEX_CONFIG_DIR': str(tmp_path)})
    external = resolve_database_url({
        'ONEIRODEX_EMBEDDED_DB': 'auto',
        'DATABASE_HOST': 'db',
        'DATABASE_URL': 'postgresql://user:password@db/example',
    })
    forced_external = resolve_database_url({
        'ONEIRODEX_EMBEDDED_DB': 'false',
        'DATABASE_URL': 'postgresql://user:password@db/example',
    })

    assert isinstance(embedded, URL)
    assert external == 'postgresql://user:password@db/example'
    assert forced_external == external


def test_external_mode_never_falls_back_to_embedded_or_test_database():
    with pytest.raises(ValueError, match='DATABASE_URL'):
        resolve_database_url({
            'ONEIRODEX_EMBEDDED_DB': 'false',
            'TEST_DATABASE_URL': 'postgresql://test-only/db',
        })
    with pytest.raises(ValueError, match='DATABASE_URL'):
        resolve_database_url({
            'ONEIRODEX_EMBEDDED_DB': 'auto',
            'DATABASE_HOST': 'db',
            'TEST_DATABASE_URL': 'postgresql://test-only/db',
        })


def test_embedded_resolution_validates_cluster_and_never_prints_password(tmp_path, monkeypatch, capsys):
    from scripts.migrate_store_credentials import main

    password = make_embedded_config(tmp_path)
    (tmp_path / 'pgdata' / 'PG_VERSION').write_text('not-a-version', encoding='ascii')
    monkeypatch.setenv('ONEIRODEX_EMBEDDED_DB', 'true')
    monkeypatch.setenv('ONEIRODEX_CONFIG_DIR', str(tmp_path))

    assert main() == 2
    output = capsys.readouterr()
    assert 'Embedded database cluster is invalid' in output.err
    assert password not in output.out + output.err


def test_embedded_resolution_requires_private_password_file(tmp_path):
    if os.name == 'nt':
        pytest.skip('POSIX file permission bits are not exposed by Windows stat')
    make_embedded_config(tmp_path)
    (tmp_path / 'secrets').chmod(0o755)

    with pytest.raises(ValueError, match='permissions'):
        resolve_database_url({
            'ONEIRODEX_EMBEDDED_DB': 'true',
            'ONEIRODEX_CONFIG_DIR': str(tmp_path),
        })
