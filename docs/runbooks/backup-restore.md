# Standalone backup and restore

> **Doc status:** Active

This runbook covers the bundled standalone installation on the same Windows,
macOS, or Linux device. The first version deliberately uses the safe offline
contract already used by the standalone move tool: stop Oneirodex, verify its
PostgreSQL cluster is stopped, then capture the database and managed user-file
generations together. Docker, Unraid, external-PostgreSQL and live online
backups are not qualified by this command.

## Create a backup

Stop Oneirodex completely. The command refuses to export if the bundled
PostgreSQL cluster is already running. Keep the bundle in an operator-controlled
location with access protection suitable for account data.

```text
python -m oneirodex_standalone backup --pg-home <bundled-postgresql> --data-dir <standalone-data> --to <new-backup-folder>
```

The output folder must be new or empty. A successful backup contains the
verified move format version 2 payload, a versioned `backup` manifest section, and
`backup.complete.json`. The completion marker binds the final manifest hash;
the database dump and each listed managed file are re-hashed before the marker
is written. Without the marker, the folder is incomplete and must not be used
as a restore source.
The backup and completion metadata use version 2, so older importers that only
recognize version 1 refuse the new format. The current importer continues to
accept verified version 1 backups.

The bundle includes the database and files under the standalone library's
managed user folders, including emulator saves and retained save generations.
It records the Alembic revision, PostgreSQL major version, source commit when
available, and save-table identity digests. It excludes external game-library
contents, BIOS files, and operator key material. External game paths are
recorded for remapping; their game files need a separate backup.

Reusable-secret and save-encryption keyrings stay outside the bundle. The
manifest records referenced key IDs and the command refuses to complete when
the database still contains reusable plaintext credentials or the configured
reusable-secret ring is missing a referenced ID. Keep a separately protected
operator backup of both keyrings. The encrypted database and personal files
remain sensitive household data; do not send the bundle to a shared location
without protecting it.

New `GTENC3` save entries include the owning user, game, slot and opaque
generation context. The importer checks that context against the restored row
and verifies the plaintext digest before accepting the restore. Legacy
`GTENC1` files are re-encrypted into this format during export; older `GTENC2`
files remain readable until the key-rotation command publishes a bound
generation.

The printed manifest SHA-256 is an integrity check, not publisher
authentication. Store the bundle and hash in a protected operator location.
Offline backups remain outside account deletion and follow the household's
separate operator retention policy; this product does not set a duration.

## Restore

Restore into a new, empty target database using the existing verified move
import procedure. Configure the target's database and library, restore the
matching protected operator keyrings first, and provide the exact manifest
fingerprint printed by the backup command:

```text
python -m oneirodex_standalone import <backup-folder> --expect <manifest-sha256> --library-dir <target-library>
```

For each external path recorded in the manifest, add its target mapping with
`--root NAME=PATH`. The importer validates the dump and files, restores to an
empty database, checks the restored rows and save readability, and refuses
missing required save keys before changing the target. Follow
[standalone-move.md](standalone-move.md) for PostgreSQL client requirements,
rollback, and restore troubleshooting.

This first standalone backup command does not restore in place, bundle key
material, include game-library contents, or establish a live server backup
barrier. Test the complete flow on a disposable target before relying on it for
recovery.
