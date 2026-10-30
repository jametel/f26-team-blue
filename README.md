# Fall 2026 - Team Blue - VibeQueue

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
During the repair, new requests can remain unassigned until venue-specific
request routing is implemented.
