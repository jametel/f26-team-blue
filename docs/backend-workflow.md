# Backend workflow

Venue owners, staff memberships, music settings, allowed or blocked genres, and song blacklists can be managed in Django admin. Assign owners and staff before using venue access controls. Each venue's public entry URL is `/venues/<slug>/`.

Song metadata is stored in `SongFeatures`. Values migrated from the old Song fields are marked `legacy-unverified` because their original source is unknown. `core.services.song_features` provides cache lookup and a refresh interface for providers. No BPM, mood, or explicit-content provider is configured yet.

The Vibe Engine checks the venue's blacklist, explicit policy, genre filters, and BPM range when a song is requested. It records the decision and reasons. Unknown values follow the venue's policy, which defaults to staff review.

Owners and assigned staff can enable or disable new requests from the venue dashboard. Request submission uses the venue's database lock to enforce duplicate and five-pending-request limits during concurrent submissions.

Staff can approve requests into the venue queue, move entries within a priority, change priority, remove entries, and mark them played. Higher priority is listed first. Marking a request played changes its status; it does not play audio.

## Tests

Install `requirements-test.txt` and run `python manage.py test` against PostgreSQL. The test dependencies include an independent QR decoder.
