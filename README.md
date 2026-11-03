# RhythmiQ

RhythmiQ is a web app for venue song requests. Guests can search and request songs without an account, while venue staff manage requests and the queue.

## Run locally

1. Install and start Docker Desktop.
2. Create a local `.env` file with `SECRET_KEY`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, and `DB_PORT`. For Docker Compose, use PostgreSQL port `5432`. Optionally set `WEB_PORT`, which defaults to `8000`.
3. Start the app:

   ```powershell
   docker compose up --build
   ```

4. Open `http://localhost:8000`, or use the port set in `WEB_PORT`.

The web service applies database migrations when it starts. Back up an existing database before starting an upgraded version. See [database upgrades](docs/database-upgrades.md) for details.

## Documentation

- [Database upgrades](docs/database-upgrades.md): backups, migrations, and legacy data.
- [Venue QR codes](docs/venue-qr-codes.md): public address configuration and phone testing.
- [Backend workflow](docs/backend-workflow.md): venue settings, Vibe Engine, queue, and tests.

Music playback and payment processing are not implemented.

## Team

- jametel - Andrew Behre - abehr003@odu.edu
- alannaiveyyy - Alanna Ivey - aivey004@odu.edu
- spencerhall11 - Spencer Hall - shall053@odu.edu
- hayeslucas1 - Lucas Hayes - Lhaye005@odu.edu
- beggl001 - Bea Eggleston - beggl001@odu.edu
- grmstudent - Gaby Macatangay - gmaca001@odu.edu
- notsosmartt-cmd - Dominick Rodriguez - drodr026@odu.edu
