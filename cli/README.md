# cli

The `omarchy-m-test` command. Python 3 standard library only.

    bin/omarchy-m-test [--dry-run] [--output FILE] [--site URL] [--catalogue FILE]
    bin/omarchy-m-test --explain REPORT [--catalogue FILE]

It refuses non-Apple machines, shows the disclaimer (Enter accepts), runs the checks, writes the report, shows it and asks before uploading it to the site (`--site http://localhost:3000` for a local site).

Every result is explained against the feature catalogue (`../catalogue/catalogue.json`; a release ships it as `omarchy_m_test/catalogue.json`): works, not yet supported by Aurora, not yet supported by Asahi, unknown hardware and so on. The report records the catalogue version. `--catalogue FILE` runs with a draft catalogue; `--explain REPORT` re-explains a saved report against the current catalogue without running anything.

## The host boundary

Every interaction with the machine, the human and the network goes through a `Host` (`omarchy_m_test/host.py`): run a command, read a file, list a directory, prompt, show, write the report, post it. `scripts/check_boundary.py` fails CI if any other module does I/O or imports outside the standard library.

Tests replace the real host with a `RecordedHost` (`omarchy_m_test/recording.py`) that replays a recording from `tests/recordings/` and scripted answers. Anything the CLI asks for that isn't recorded raises `RecordingMiss`.

## Test (Seam A)

    python3 scripts/check_boundary.py
    python3 -m unittest discover -s tests -t .

Reports produced here must equal the golden reports in `../schema/golden/`, which the site's Seam B tests post to the API.
