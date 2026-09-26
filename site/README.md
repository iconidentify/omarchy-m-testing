# site

The omarchy-m-testing.org site and upload API (Rails 8, Postgres).

- `POST /api/v1/reports`: upload a report; it must validate against `../schema/report-v1.schema.json` and use only check ids the feature catalogue knows. Returns `201` with `report_url` and `deletion_url`, `422` with `details` when it doesn't match the schema or has unknown check ids, `400` when the body isn't JSON.
- `GET /install`: the one-line installer, `../installer/install.sh` (override with `INSTALLER_PATH`). `GET /`: the home page.
- `www.` + `CANONICAL_HOST` (default `omarchy-m-testing.org`) redirects to the apex.
- `GET /reports/:id`: the report page. `GET /reports/:id/deletion?token=...`: the deletion link.

The schema is read from `../schema` (override with `REPORT_SCHEMA_DIR`) and the feature catalogue from `../catalogue/catalogue.json` (override with `CATALOGUE_PATH`).

## Develop

Postgres connection settings come from `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD` (production: `DATABASE_URL`).

    bundle install
    bin/rails db:prepare
    bin/rails test        # Seam B
    bin/rails server

## Deploy

Railway builds `Dockerfile` from the repository root (`railway.json`), so the schema, catalogue and installer sit next to `site/` in the image and no path overrides are needed. `bin/rails db:prepare` runs before each deploy; `/up` is the health check. Production variables: `DATABASE_URL` (from the Postgres service), `SECRET_KEY_BASE`.
