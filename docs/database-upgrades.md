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
