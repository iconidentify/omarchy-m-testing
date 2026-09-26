# cli

The `omarchy-m-test` command. Python 3 standard library only.

    bin/omarchy-m-test [--dry-run] [--output FILE] [--site URL] [--catalogue FILE] [--record FILE]
    bin/omarchy-m-test --explain REPORT [--catalogue FILE]

It refuses non-Apple machines, shows the disclaimer (Enter accepts), runs the checks, writes the report, shows it and asks before uploading it to the site (`--site http://localhost:3000` for a local site).

## Automatic checks

A run checks the boot chain and encryption, packages and first-boot hardware setup, GPU driver and Vulkan/OpenGL, displays, audio routing and speaker protection, Wi-Fi and Bluetooth, snapshots, battery and CPU frequency scaling (`ORDER` in `omarchy_m_test/checks.py`; every id is in the catalogue's `checks`).

Most come from omarchy-mac's own check scripts, wrapped rather than duplicated (`omarchy_m_test/scripts.py`): `mac-check` on every stack, and `apple-audio-check.sh --no-sound` and `apple-display-check.sh --read-only` on the converged image they were written for. Their PASS/FAIL/SKIP lines become results with the lines as evidence. mac-check runs its root-only checks through `sudo -n`, so without passwordless sudo they are skipped, never failed; the CLI itself never asks for a password. The rest (`omarchy_m_test/hardware.py`) read sysfs, the journal and pacman.

The scripts are vendored, unmodified, in `omarchy_m_test/vendor/omarchy-mac/` (commit and hashes in `ORIGIN`), and a release ships them. No stack installs them: `mac-check` lives in omarchy-mac's `tools/hardware/` and the others in `test/manual/`, so there is no installed copy to call, and a pinned copy keeps the parsed lines stable between releases. Once the tool ships inside the omarchy-mac package (after quattro-upstream lands), the package can carry the scripts and `bundled.py` point at them.

The report's `system` block records the stack (`converged` for the omarchy-mac or omarchy package, `mx-mac` for the fork's `omarchy-dev`, `legacy-omarchy-mac` for a checkout, or `reference` for another distro, where Omarchy-layer results are skipped), the os-release ID, the boot loader, whether the root filesystem is encrypted, and the versions of the stack, boot and hardware packages. On a candidate image, whose target record (`/var/lib/omarchy/image/target`, retired to `target.booted` by the first boot) is present, it also records the candidate set: the record's `candidate_set`, else the factory seal's (`/var/lib/omarchy/factory-sealed`, on the root after a factory reset). The image builder doesn't write `candidate_set` into the target record yet, so a freshly installed candidate image carries no tag until it does.

Every result is explained against the feature catalogue (`../catalogue/catalogue.json`; a release ships it as `omarchy_m_test/catalogue.json`): works, not yet supported by Aurora, not yet supported by Asahi, unknown hardware and so on. The report records the catalogue version. `--catalogue FILE` runs with a draft catalogue; `--explain REPORT` re-explains a saved report against the current catalogue without running anything.

Before each run it looks up the latest release's version (`releases/latest/download/VERSION` on GitHub, 5 s timeout) and says so when a newer one exists, with the command to upgrade. Offline or any odd answer: it says nothing and carries on.

## The host boundary

Every interaction with the machine, the human and the network goes through a `Host` (`omarchy_m_test/host.py`): run a command, read a file, list a directory, prompt, show, write the report, post it, GET the latest version. `scripts/check_boundary.py` fails CI if any other module does I/O or imports outside the standard library.

Tests replace the real host with a `RecordedHost` (`omarchy_m_test/recording.py`) that replays a recording from `tests/recordings/` and scripted answers. Anything the CLI asks for that isn't recorded raises `RecordingMiss`.

## Privacy

Every report passes `omarchy_m_test/privacy.py` before it is written, shown or uploaded: only the allowlisted fields (the same tree as `schema/report-v1.schema.json`) reach it, and every evidence line is scrubbed of MAC and IP addresses, Wi-Fi network names, home paths, hostnames, usernames, e-mail addresses, serial numbers, UUIDs and long hex identifiers. Evidence is text only and at most 64 KiB per report; the site refuses reports that break either rule.

## Recording a Mac

    bin/omarchy-m-test --dry-run --record my-mac.json

Record mode runs as usual and also saves what the Mac answered at the host boundary: every command, file and directory the CLI read, plus the sources later checks need (`RECORDED_SOURCES` in `recording.py`: kernel log, device tree, first-boot, Wi-Fi and lid journals, uname, PCI, input devices, addresses). The recording is scrubbed before it is saved. Prompts, answers and uploads are not recorded. Check a new recording by eye before committing it, then add it to `tests/recordings/`.

`tests/corpus/` holds the real M1 and M2 evidence the seeded recordings came from, pseudonymized (every identifier swapped for a same-shape decoy) because this repository is public. Answers never captured on a Mac (most of the M1's, and the M2's mac-check output) are reconstructed from what is known of the install and say so in their `note`; the v0.1 dogfood run replaces them. `scripts/reseed_recordings.py` reruns record mode over the corpus and rewrites `tests/recordings/` and the golden reports.

## Test (Seam A)

    python3 scripts/check_boundary.py
    python3 -m unittest discover -s tests -t .

The corpus tests run the whole CLI in record mode against the real evidence and fail if any identifier listed in a corpus machine's `forbidden`, or any MAC, IP, UUID, long hex id or home path, reaches a recording or a report. Reports produced here must equal the golden reports in `../schema/golden/`, which the site's Seam B tests post to the API.
