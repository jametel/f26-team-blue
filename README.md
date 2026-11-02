# Fall 2026 - Team Blue - RhythmiQ

# Members

- jametel - Andrew Behre - abehr003@odu.edu
- alannaiveyyy - Alanna Ivey - aivey004@odu.edu
- spencerhall11- Spencer Hall -shall053@odu.edu
- hayeslucas1 - Lucas Hayes - Lhaye005@odu.edu
- beggl001 - Bea Eggleston - beggl001@odu.edu
- grmstudent - Gaby Macatangay - gmaca001@odu.edu
- notsosmartt-cmd - Dominick Rodriguez - drodr026@odu.edu

## Database upgrade

Back up existing databases before applying migrations. The safe replacement for
`core` migration 0005 preserves request owners and guest sessions when upgrading
from 0004. Requests without a known venue remain unassigned until a venue is
chosen; the app does not assume venue ID 1.

If the original 0005 was already applied, its removal of requester and session
fields cannot be reversed without a backup. It may also have assigned old
requests to user or venue ID 1. Check those associations before relying on them.
Migration 0007 restores identity only where the safe replacement saved it.
Existing unassigned requests are marked as legacy and can be assigned to a
venue in Django admin. New requests require a venue.

Venue owners, staff memberships, music settings, allowed or blocked genres,
and song blacklists can be managed in Django admin. Existing venues receive a
public slug during migration. Assign their owners before using venue access
controls. The Vibe Engine enforces the unknown-song policy, which defaults to
staff review.

Each venue's public entry URL is `/venues/<slug>/`. Staff and owners select a
venue before opening its dashboard. Assign owners and staff in Django admin.

## Venue QR codes

Set `PUBLIC_BASE_URL` in `.env` to the HTTP or HTTPS origin that guests can
reach, including the port when needed, for example `http://192.168.1.10:8901`.
Do not include a path or credentials. For a network address, add the hostname
or IP address to the comma-separated `ALLOWED_HOSTS` setting in `.env` and
make sure the phone and server can communicate. `localhost` on a phone means
the phone itself, not the computer running Django. Restart the web service
after changing its environment.

Owners and venue staff can open and download a QR code from their dashboard.
Changing the public address or venue slug requires printing a new code. The
QR code opens the venue's guest search page and does not require an account.

For all automated tests, including independent QR decoding, install
`requirements-test.txt` and run `python manage.py test` against PostgreSQL.

Song metadata is stored in `SongFeatures`. Values migrated from the old Song
fields are marked `legacy-unverified` because their original source is unknown.
`core.services.song_features` provides cache lookup and a refresh interface for
providers. No BPM, mood, or explicit-content provider is configured yet.

The Vibe Engine checks the venue's blacklist, explicit policy, genre filters,
and BPM range when a song is requested. It records the decision and reasons.
Unknown values follow the venue's policy, which defaults to staff review.

Owners and assigned staff can enable or disable new song requests from the
venue dashboard. Existing venues start enabled after migration. Disabling new
requests does not remove existing requests or queue entries.
Request submission uses the venue's database lock to enforce the existing
duplicate and five-pending-request limits during concurrent submissions.

Staff can approve requests into the venue queue, move entries within a priority,
change priority, remove entries, and mark them played. Higher priority is listed
first. Queue positions are protected against concurrent updates. The queue
migration stops for duplicate, cross-venue, or non-approved legacy entries so
they can be resolved without silently deleting data.
