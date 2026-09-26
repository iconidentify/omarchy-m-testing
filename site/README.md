# site

The omarchy-m-testing.org site and upload API (Rails 8, Postgres).

- `POST /api/v1/reports`: upload a report; it must validate against `../schema/report-v1.schema.json`. Returns `201` with `report_url` and `deletion_url`, `422` with `details` when it doesn't match the schema, `400` when the body isn't JSON.
- `GET /reports/:id`: the report page. `GET /reports/:id/deletion?token=...`: the deletion link.

The schema is read from `../schema` (override with `REPORT_SCHEMA_DIR`).

## Develop

Postgres connection settings come from `PGHOST`, `PGPORT`, `PGUSER`, `PGPASSWORD` (production: `DATABASE_URL`).

    bundle install
    bin/rails db:prepare
    bin/rails test        # Seam B
    bin/rails server
