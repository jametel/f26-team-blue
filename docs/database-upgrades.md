# Database upgrades

Back up an existing database before applying migrations. Docker Compose runs migrations automatically when the web service starts.

For a running local Docker database, the following PowerShell commands create a timestamped backup in your Windows user folder:

```powershell
$tag = Get-Date -Format 'yyyyMMdd-HHmmss'
docker compose exec -T -e "BACKUP_NAME=rhythmiq-$tag.dump" db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f "/tmp/$BACKUP_NAME"'
docker compose cp "db:/tmp/rhythmiq-$tag.dump" "$env:USERPROFILE\rhythmiq-$tag.dump"
Test-Path "$env:USERPROFILE\rhythmiq-$tag.dump"
```

Check that the backup commands succeed and the final command returns `True` before proceeding. A file existence check alone does not verify a restore.

To apply migrations to a running web service:

```powershell
docker compose exec web python manage.py migrate
```

## Existing data

The safe replacement for `core` migration 0005 preserves request owners and guest sessions when upgrading from 0004. Requests without a known venue remain unassigned until a venue is chosen; the app does not assume venue ID 1.

If the original 0005 was already applied, its removal of requester and session fields cannot be reversed without a backup. It may also have assigned old requests to user or venue ID 1. Check those associations before relying on them. Migration 0007 restores identity only where the safe replacement saved it. Existing unassigned requests are marked as legacy and can be assigned to a venue in Django admin.

Migration 0018 adds request availability. Existing venues start with requests enabled. Disabling new requests does not remove existing requests or queue entries.

The queue migration stops if legacy entries are duplicate, cross-venue, or not approved, so the entries can be resolved without silently deleting data.

## Song identifiers in migration 0019

Migration 0019 has been corrected to copy each old MusicBrainz ID into the song primary key and update related song references in the same transaction before removing the old field. This intentionally changes the existing migration file. Databases that already recorded 0019 will not rerun it. Back up and verify the backup before upgrading. The migration stops rather than guessing if an old ID is empty, longer than 36 characters, or conflicts with another target.

For a database that has not applied 0019, deploy the corrected code before running migrations. Test the upgrade on a restored copy first and verify songs, requests, decisions, features and queue entries. Because the schema and song keys change, restore the backup to undo the upgrade rather than reversing the migration on a populated database.

### Databases that already applied 0019

The removed IDs cannot be recovered from the upgraded database alone. Restore a pre-0019 backup into a separate temporary database and export its song `id` and `musicbrainz_id` columns as a CSV with the header `old_id,musicbrainz_id`. Verify that each old ID still identifies the same song in the current database, including title and artist. Do not assume a backup matches if records were changed or database history differs. The file may contain only the verified songs to restore. On the restored pre-0019 database, this SQL exports the mapping:

```sql
COPY (SELECT id AS old_id, musicbrainz_id FROM core_song ORDER BY id) TO STDOUT WITH CSV HEADER;
```

Copy the verified CSV into the web container, then validate it without saving changes. For example, if the file is named `song-map.csv` in the current PowerShell directory:

```powershell
docker compose cp .\song-map.csv web:/tmp/song-map.csv
docker compose exec web python manage.py restore_song_identifiers /tmp/song-map.csv
```

The dry run checks song existence, identifier length and conflicts and rolls the transaction back. After independently verifying the mapping and restoring the backup on a disposable copy to rehearse the operation, apply it to the intended database:

```powershell
docker compose exec web python manage.py restore_song_identifiers /tmp/song-map.csv --apply
```

Stop other application writes during recovery. The command updates song keys and all related song foreign keys atomically; collisions or invalid entries stop the operation. Confirm requests, queue entries, decisions and search afterward. Keep the original backup and remove temporary copies only when they are no longer needed. If a mapping is unavailable, the original identifiers cannot be restored reliably; do not invent them.
