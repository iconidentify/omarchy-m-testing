# site

The omarchy-m-testing.org site and upload API (Rails 8, Postgres).

- `POST /api/v1/reports`: upload a report; it must validate against `../schema/report-v1.schema.json` and use only check ids the feature catalogue knows. Returns `201` with `report_url` and `deletion_url`, `422` with `details` when it doesn't match the schema, uses an outdated schema version or has unknown check ids (both with upgrade instructions), `422` when it isn't signed by its machine's key or its signature doesn't match it, `400` when the body isn't JSON, `429` past `UPLOADS_PER_HOUR` (default 30) uploads an hour from one IP address or `UPLOADS_PER_HOUR_PER_MACHINE` (default 10) from one machine key.
- Pages: `/` (install and the matrix), `/matrix` (model × stack/version, `?stack=` filters), `/models/:board`, `/features/:id`, `/gaps` (kernel gaps, and the regressions still open), `/aurora` (the Aurora feature-support table), `/benchmarks` (benchmark scores per model and stack/version: each machine once, with its latest score, the median per row, compared only within one check, suite and unit; also on each model page and report), `/reports`, `/reports/:id` (terminal-style), `/data`.
- Exports, CC0, visible reports only: `/api/v1/reports.json` (every report as uploaded), `/api/v1/reports.csv` (one row per report), `/api/v1/checks.csv` (one row per check, with any benchmark score), `/api/v1/matrix.json`, `/api/v1/benchmarks.json`, `/api/v1/aurora.json`.
- `GET /install`: the one-line installer, `../installer/install.sh` (override with `INSTALLER_PATH`).
- `www.` + `CANONICAL_HOST` (default `omarchy-m-testing.org`) redirects to the apex.
- `GET /reports/:id/deletion?token=...`: the deletion link; deleting removes the report row and with it all its evidence.
- `POST /api/v1/tester_bindings`: tester sign-in (`omarchy-m-test --sign-in`). The body is `{"binding_version": 1, "github_token": ..., "signature": ...}`, signed by the machine key like a report but under the namespace `omarchy-m-test-tester`. GitHub confirms the token was issued by the site's OAuth app and names its user (`POST /applications/{client_id}/token`, with the client secret); the machine key is bound to that handle (`tester_bindings`, signing in again rebinds) and the token is revoked, never stored. An allowlisted handle is pinned to the GitHub account that first signs in with it (renamed handles get reissued), so a later owner of the handle is refused (`403`). `201` with `login` and `tester` (on the allowlist or not), `422` for anything else or a bad signature, `401` when GitHub doesn't confirm the token, `503` without the GitHub app, `429` past `SIGN_INS_PER_HOUR` (default 10) from one network.
- `/candidates`, `/candidates/:name`: runs per candidate set (`system.candidate_set`), with the tester results per model and feature and whether the set is ready for promotion: waiting (no tester run), blocked (tester runs found a feature failing where it should work, a regression or not, listed) or ready.
- `/admin`: sign in with GitHub (the OAuth app's web flow, callback `/auth/github/callback`) as a handle in `ADMIN_GITHUB_LOGINS` to hide, show again or delete any report and manage the tester allowlist (`/admin/testers`: add or remove handles, see and unbind signed-in machines). Taking a handle out of `ADMIN_GITHUB_LOGINS` signs it out. Until GitHub sign-in is set up (`GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` and `ADMIN_GITHUB_LOGINS`), the v0.1 secret `ADMIN_TOKEN` still signs in; once it is, the token is ignored. With neither there is no admin.

Aggregation: community reports show up at once; a matrix cell takes a colour only when two or more distinct machines agree (each machine counted once, with the latest state it tested), or at once from tester runs: the state the tester machines agree on, partial when they disagree (framed, `data-verified="tester"`). A tester run is a report from a machine bound to a GitHub handle when it was uploaded (`reports.tester_login`) while that handle is on the allowlist (`testers`, which starts with the owner); it gets the tester badge. The handle is shown only to the admin. A machine is its signing key: every report is signed by a per-machine ed25519 key the CLI creates on its first run (`ssh-keygen -Y sign`, verified with Ruby's OpenSSL in `app/models/machine_signature.rb`), and `reports.machine_id` is `key:` and a keyed digest of the public key. The key and the signature are not stored, shown or exported. Reports uploaded before machine keys keep `ip:` ids, a keyed digest of the uploader's network.

Regressions: a failure (outcome `fails`) is a regression only when a verified earlier run on the same Mac model (board) and stack passed that feature: a visible tester run uploaded before it in which the feature worked, whatever its Omarchy version. Without one it stays "doesn't work", so a user's setup error isn't taken for a regression. The report page marks a regression and links that pass; `/gaps` lists the regressions still open (the newest run testing the feature on that model and stack is one).

Aurora feature-support table (`/aurora`, `/api/v1/aurora.json`): per catalogue chip generation, the Asahi- and Aurora-layer features from visible tester runs with the `linux-aurora` package, each tester machine counted once with its latest run that tested the feature (partial when testers disagree), next to the catalogue's expected Aurora and Asahi states, with the runs behind each cell and the Aurora versions they ran. Chip generations without such a run are listed as not yet verified.

Issues: the signed-in admin sees an "open issue" link on every failing or gap check of a visible report and on every row of `/gaps` (regressions, gaps found on real Macs, unclaimed hardware, catalogue gaps). It opens GitHub's new-issue page prefilled with a title and a body linking the reports, on `omacom/linux` for the Asahi hardware and Aurora layers (and unclaimed hardware) or `omacom/omarchy-mac` for Omarchy integration. The admin files it; the site makes no GitHub API call.

The per-network limit reads the client address from `X-Real-IP` behind Railway's edge (`CLIENT_IP_HEADER` overrides it in any environment). Railway's edge overwrites a client-sent `X-Real-IP` (checked against production: uploads each claiming a different `X-Real-IP` still shared one limit); `X-Forwarded-For` isn't used, since Railway doesn't document whether it strips or appends a client-sent one. Keep Railway's CDN off for the site: behind it `X-Real-IP` is the CDN's address.

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
- Variables: `DATABASE_URL=${{Postgres.DATABASE_URL}}`, `SECRET_KEY_BASE`, `GITHUB_CLIENT_SECRET` and (until GitHub sign-in is set up) `ADMIN_TOKEN` (secrets, only in Railway: `railway variables --service site --kv`), `GITHUB_CLIENT_ID` (the `omarchy-m-testing` OAuth app on the owner's GitHub account, device flow enabled; the CLI ships the same ID), `ADMIN_GITHUB_LOGINS=maralcbr`, `RAILS_MAX_THREADS=3`.
- Domains: `omarchy-m-testing.org` and `www.omarchy-m-testing.org` (DNS at Porkbun; `www` redirects to the apex in the app).

## Design

Omarchy's design language, from omarchy.org: the Tokyo Night palette, JetBrains Mono (self-hosted from `app/assets/fonts`, SIL Open Font License in `JetBrainsMono-OFL.txt`), the Omarchy logo (`app/assets/images/omarchy-logo.svg`, from omarchy.org's brand page, used with the Omarchy project's permission) and terminal cards. Colour code: green works, yellow partial, orange doesn't work (though it should), red regression, blue expected missing, magenta unknown hardware, grey not tested; outlined while community reports are unconfirmed.
