# cli

The `omarchy-m-test` command. Python 3 standard library only.

    bin/omarchy-m-test [--dry-run] [--output FILE] [--site URL] [--catalogue FILE] [--record FILE]
    bin/omarchy-m-test --explain REPORT [--catalogue FILE]

It refuses non-Apple machines, shows the disclaimer (Enter accepts), runs the checks, writes the report, shows it and asks before uploading it to the site (`--site http://localhost:3000` for a local site).

Every result is explained against the feature catalogue (`../catalogue/catalogue.json`; a release ships it as `omarchy_m_test/catalogue.json`): works, not yet supported by Aurora, not yet supported by Asahi, unknown hardware and so on. The report records the catalogue version. `--catalogue FILE` runs with a draft catalogue; `--explain REPORT` re-explains a saved report against the current catalogue without running anything.

## The host boundary

Every interaction with the machine, the human and the network goes through a `Host` (`omarchy_m_test/host.py`): run a command, read a file, list a directory, prompt, show, write the report, post it. `scripts/check_boundary.py` fails CI if any other module does I/O or imports outside the standard library.

Tests replace the real host with a `RecordedHost` (`omarchy_m_test/recording.py`) that replays a recording from `tests/recordings/` and scripted answers. Anything the CLI asks for that isn't recorded raises `RecordingMiss`.

## Privacy

Every report passes `omarchy_m_test/privacy.py` before it is written, shown or uploaded: only the allowlisted fields (the same tree as `schema/report-v1.schema.json`) reach it, and every evidence line is scrubbed of MAC and IP addresses, Wi-Fi network names, home paths, hostnames, usernames, e-mail addresses, serial numbers, UUIDs and long hex identifiers. Evidence is text only and at most 64 KiB per report; the site refuses reports that break either rule.

## Recording a Mac

    bin/omarchy-m-test --dry-run --record my-mac.json

Record mode runs as usual and also saves what the Mac answered at the host boundary: every command, file and directory the CLI read, plus the sources later checks need (`RECORDED_SOURCES` in `recording.py`: kernel log, device tree, first-boot, Wi-Fi and lid journals, uname, PCI, input devices, addresses). The recording is scrubbed before it is saved. Prompts, answers and uploads are not recorded. Check a new recording by eye before committing it, then add it to `tests/recordings/`.

`tests/corpus/` holds the real M1 and M2 evidence the seeded recordings came from, pseudonymized (every identifier swapped for a same-shape decoy) because this repository is public. `scripts/reseed_recordings.py` reruns record mode over it and rewrites `tests/recordings/`.

## Test (Seam A)

    python3 scripts/check_boundary.py
    python3 -m unittest discover -s tests -t .

The corpus tests run the whole CLI in record mode against the real evidence and fail if any identifier listed in a corpus machine's `forbidden`, or any MAC, IP, UUID, long hex id or home path, reaches a recording or a report. Reports produced here must equal the golden reports in `../schema/golden/`, which the site's Seam B tests post to the API.
