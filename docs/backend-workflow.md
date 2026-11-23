# Backend workflow

Venue owners, staff memberships, music settings, allowed or blocked genres, and song blacklists can be managed in Django admin. Assign owners and staff before using venue access controls. Each venue's public entry URL is `/venues/<slug>/`.

Song metadata is stored in `SongFeatures`. Values migrated from the old Song fields are marked `legacy-unverified` because their original source is unknown. `core.services.song_features` provides cache lookup and a refresh interface for providers. No BPM, mood, or explicit-content provider is configured yet.

The Vibe Engine checks the venue's blacklist, explicit policy, genre filters, and BPM range when a song is requested. It records the decision and reasons. Unknown values follow the venue's policy, which defaults to staff review.

Owners and assigned staff can enable or disable new requests from the venue dashboard. Request submission uses the venue's database lock to enforce duplicate and five-pending-request limits during concurrent submissions.

Staff can approve requests into the venue queue, move entries within a priority, change priority, remove entries, and mark them played. Higher priority is listed first. Marking a request played changes its status; it does not play audio.

## Tests

Install `requirements-test.txt` and run `python manage.py test` against PostgreSQL. The test dependencies include an independent QR decoder.

## Demo walkthrough

Prepare a venue, an assigned staff account and a saved song. Open the venue link as a guest, search for the song and submit a request. Missing required metadata follows the venue's unknown-song policy and defaults to staff review. In a separate staff session, select the venue and approve the request. The song appears in the approved queue and the guest sees Approved after refreshing My Requests. Marking played changes a status; it does not play audio.

For a phone to scan a venue QR code, configure `PUBLIC_BASE_URL` and `ALLOWED_HOSTS` as described in `docs/venue-qr-codes.md`. Capture screenshots after rehearsing the flow on the presentation machine.

## Song search and metadata

Search uses locally cached songs first and queries MusicBrainz when no local match exists. The Search more songs button also queries MusicBrainz and combines results with cached songs, deduplicating by recording ID. Cached results remain available if the provider fails. Results display MusicBrainz recording descriptions when available. Results sharing a title and artist also show their recording IDs because they can represent different recordings. Some recordings have no description, so their version may remain unclear.

The Vibe Engine reads `SongFeatures`, not the search result's inferred fields. Missing or unverified features follow the venue's unknown-song policy, which defaults to staff review. MusicBrainz search does not provide a verified explicit-content flag or BPM; no trusted automatic feature provider is configured.
