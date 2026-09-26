# site

The omarchy-m-testing.org site and upload API (Rails 8, Postgres).

- `POST /api/v1/reports`: upload a report; it must validate against `../schema/report-v1.schema.json` and use only check ids the feature catalogue knows. Returns `201` with `report_url` and `deletion_url`, `422` with `details` when it doesn't match the schema, uses an outdated schema version or has unknown check ids (both with upgrade instructions), `400` when the body isn't JSON, `429` past `UPLOADS_PER_HOUR` (default 30) uploads an hour from one IP address.
- Pages: `/` (install and the matrix), `/matrix` (model × stack/version, `?stack=` filters), `/models/:board`, `/features/:id`, `/gaps` (kernel gaps), `/reports`, `/reports/:id` (terminal-style), `/data`.
- Exports, CC0, visible reports only: `/api/v1/reports.json` (every report as uploaded), `/api/v1/reports.csv` (one row per report), `/api/v1/checks.csv` (one row per check), `/api/v1/matrix.json`.
- `GET /install`: the one-line installer, `../installer/install.sh` (override with `INSTALLER_PATH`).
- `www.` + `CANONICAL_HOST` (default `omarchy-m-testing.org`) redirects to the apex.
- `GET /reports/:id/deletion?token=...`: the deletion link; deleting removes the report row and with it all its evidence.
- `/admin`: sign in with the secret `ADMIN_TOKEN` to hide, show again or delete any report. Without `ADMIN_TOKEN` there is no admin. Changing it signs the admin out.

Aggregation: community reports show up at once; a matrix cell takes a colour only when two or more distinct machines agree (each machine counted once, with the latest state it tested). Until reports carry machine keys (ticket 09), a machine is a keyed digest of the uploader's IP address (`reports.machine_id`, never shown or exported). Behind Railway's edge the client address is read from `X-Real-IP` (`CLIENT_IP_HEADER` overrides it in any environment).

The schema is read from `../schema` (override with `REPORT_SCHEMA_DIR`) and the feature catalogue from `../catalogue/catalogue.json` (override with `CATALOGUE_PATH`).

## Develop

Postgres connection settings come from `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD` (production: `DATABASE_URL`).

    bundle install
    bin/rails db:prepare
    bin/rails test        # Seam B (on macOS, OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES PGGSSENCMODE=disable keep forked test workers from hanging)
    bin/rails server

## Deploy

Railway project `omarchy-m-testing`, service `site` (plus a `Postgres` service), connected to this GitHub repo and deploying every push to `main`. Railway no longer reads `railway.json` for new services, so these settings live on the service itself:

- Build: `site/Dockerfile`, context the repository root (variable `RAILWAY_DOCKERFILE_PATH=site/Dockerfile`), so the schema, catalogue and installer sit next to `site/` in the image and no path overrides are needed.
- Pre-deploy command `bin/rails db:prepare`; health check `/up` (120 s).
- Watch paths: `site/**`, `schema/**`, `catalogue/catalogue.json`, `installer/install.sh`.
- Variables: `DATABASE_URL=${{Postgres.DATABASE_URL}}`, `SECRET_KEY_BASE` and `ADMIN_TOKEN` (secrets, only in Railway: `railway variables --service site --kv`), `RAILS_MAX_THREADS=3`.
- Domains: `omarchy-m-testing.org` and `www.omarchy-m-testing.org` (DNS at Porkbun; `www` redirects to the apex in the app).

## Design

Omarchy's design language, from omarchy.org: the Tokyo Night palette, JetBrains Mono (self-hosted from `app/assets/fonts`, SIL Open Font License in `JetBrainsMono-OFL.txt`), the Omarchy logo (`app/assets/images/omarchy-logo.svg`, from omarchy.org's brand page, used with the Omarchy project's permission) and terminal cards. Colour code: green works, yellow partial, red regression (doesn't work though it should), blue expected missing, magenta unknown hardware, grey not tested; outlined while community reports are unconfirmed.
