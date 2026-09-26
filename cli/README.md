# cli

The `omarchy-m-test` command. Python 3 standard library only.

    bin/omarchy-m-test [--dry-run] [--output FILE] [--site URL] [--catalogue FILE] [--record FILE] [--skip SECTION]
    bin/omarchy-m-test --explain REPORT [--catalogue FILE]

It refuses non-Apple machines, shows the disclaimer (Enter accepts), runs the checks, writes the report, shows it and asks before uploading it to the site (`--site http://localhost:3000` for a local site).

## Automatic checks

A run checks the boot chain and encryption, packages and first-boot hardware setup, GPU driver and Vulkan/OpenGL, displays, audio routing and speaker protection, Wi-Fi and Bluetooth, snapshots, battery and CPU frequency scaling (`ORDER` in `omarchy_m_test/checks.py`; every id is in the catalogue's `checks`).

Most come from omarchy-mac's own check scripts, wrapped rather than duplicated (`omarchy_m_test/scripts.py`): `mac-check` on every stack, and `apple-audio-check.sh --no-sound` and `apple-display-check.sh --read-only` on the converged image they were written for. Their PASS/FAIL/SKIP lines become results with the lines as evidence. mac-check runs its root-only checks through `sudo -n`, so without passwordless sudo they are skipped, never failed. The CLI only ever asks for a password to install temporary test packages the user agreed to (below). The rest (`omarchy_m_test/hardware.py`) read sysfs, the journal and pacman.

The scripts are vendored, unmodified, in `omarchy_m_test/vendor/omarchy-mac/` (commit and hashes in `ORIGIN`), and a release ships them. No stack installs them: `mac-check` lives in omarchy-mac's `tools/hardware/` and the others in `test/manual/`, so there is no installed copy to call, and a pinned copy keeps the parsed lines stable between releases. Once the tool ships inside the omarchy-mac package (after quattro-upstream lands), the package can carry the scripts and `bundled.py` point at them.

The report's `system` block records the stack (`converged` for the omarchy-mac or omarchy package, `mx-mac` for the fork's `omarchy-dev`, `legacy-omarchy-mac` for a checkout, or `reference` for another distro, where Omarchy-layer results are skipped), the os-release ID, the boot loader, whether the root filesystem is encrypted, and the versions of the stack, boot and hardware packages. On a candidate image, whose target record (`/var/lib/omarchy/image/target`, retired to `target.booted` by the first boot) is present, it also records the candidate set: the record's `candidate_set`, else the factory seal's (`/var/lib/omarchy/factory-sealed`, on the root after a factory reset). The image builder doesn't write `candidate_set` into the target record yet, so a freshly installed candidate image carries no tag until it does.

Every result is explained against the feature catalogue (`../catalogue/catalogue.json`; a release ships it as `omarchy_m_test/catalogue.json`): works, not yet supported by Aurora, not yet supported by Asahi, unknown hardware and so on. The report records the catalogue version. `--catalogue FILE` runs with a draft catalogue; `--explain REPORT` re-explains a saved report against the current catalogue without running anything.

Before each run it looks up the latest release's version (`releases/latest/download/VERSION` on GitHub, 5 s timeout) and says so when a newer one exists, with the command to upgrade. Offline or any odd answer: it says nothing and carries on.

## Hardware inventory and gap map

The Hardware section (`omarchy_m_test/inventory.py`) maps the Mac's hardware on every run, read-only:

- **Nodes.** Every device-tree node's `compatible` and `status` properties and nothing else (`grep` over `/sys/firmware/devicetree/base`), and which node each device came from and whether a driver is bound to it (the `OF_FULLNAME` and `DRIVER` lines of the uevents under `/sys/devices`). A node is `bound`, `unbound` (it has a device no driver claimed) or `none` (no device of its own: disabled, set up early by the kernel core, or handled by its parent's driver). `/cpus`, `/chosen` and `/reserved-memory` are left out: the kernel core handles them without drivers.
- **Unclaimed hardware.** An enabled node whose device no driver claimed is explained against the catalogue's `hardware` map (compatible pattern to feature): that feature failing, or **unknown hardware** when the catalogue doesn't know it. Bus and register containers (`simple-bus`, `simple-mfd`, `syscon`, such as the power manager) usually have no driver of their own and are never unclaimed.
- **Firmware and probe errors.** This boot's firmware-load failures and driver probe errors (`probe with driver ... failed`, `deferred probe pending`) from `journalctl --dmesg`, kept as scrubbed evidence without the journal's line prefix.
- **Build options.** `/proc/config.gz` compared with Asahi's pinned reference configuration (`../catalogue/asahi-kernel/`; a release ships it as `omarchy_m_test/asahi-kernel/`). Options set to `y`, `m`, not set or a number are compared; strings and toolchain-derived options are not. Every difference is reported; none is judged.

Its four results are `hardware.drivers`, `hardware.firmware`, `hardware.probe-errors` and `hardware.kernel-config`. The report's `inventory` block holds only node types (the first compatible string), statuses, driver-bound states and counts, the unclaimed nodes with their classification, and the build-option differences: never a property value or a node's path. Skipping the section leaves the block out.

## The run: sections, resume, restore

A run is a list of sections (`omarchy_m_test/sections.py`: boot, hardware, graphics, display, audio, network, input, power, cpu), listed up front after the disclaimer. mac-check feeds several of them and runs once, for the first one that isn't skipped. Any can be skipped: untick it in the picker at a terminal, or `--skip NAME` (repeatable, or comma-separated) anywhere. A skipped section's checks are reported as skipped.

After each section the run's state is checkpointed to `$XDG_STATE_HOME/omarchy-m-test/checkpoint.json` (`~/.local/state/...`). A run interrupted by Ctrl-C, a closed terminal or a crash offers to resume on the next start with the same tool, catalogue, Mac and kernel: finished sections aren't run again. Evidence is scrubbed before it is checkpointed, and the file is only the user's (0600, in a 0700 directory). The checkpoint is removed once the report is written, or when the disclaimer is declined. Record mode never checkpoints.

A check that changes the machine does it through the restorer registry (`omarchy_m_test/session.py`: `Context.change(description, change, restore)`), which records the undo command before making the change. Restorers run newest first when the section ends, on an error and on Ctrl-C, SIGTERM or SIGHUP; they are also kept in the checkpoint, so a run killed outright has them run by the next run before anything else. A restorer that fails is reported with the command to run by hand.

## Interactive checks and safety

The framework the interactive sections build on:

- **Human checks** (`omarchy_m_test/human.py`): `human.check(ctx, id, question, evidence)` asks yes, no or skip with an optional note (`n the left speaker crackles`; at an Omarchy terminal a gum choice, then a gum input). Yes passes, no fails, skip or no answer is skipped, never a failure. The result has kind `human`; its evidence holds the question, the answer and the note, scrubbed like any evidence. List the id in the catalogue's checks and in the section's `human_checks`.
- **SSH and the local seat** (`omarchy_m_test/presence.py`): a section with `disruptive=True` (it could cut the connection or the session) is skipped with the reason, in the section list and in the report, when the run is over SSH (`SSH_CONNECTION`/`SSH_CLIENT`/`SSH_TTY`, or logind says the session is remote) or the session has no seat or isn't active on it (`loginctl show-session`).
- **Restorers for volume and Wi-Fi** (`omarchy_m_test/changes.py`): `set_volume(ctx, level)` caps at 30%, unmutes, and puts the default sink's volume and mute back; `drop_wifi(ctx)` soft-blocks Wi-Fi with rfkill only when it's connected (a known network it rejoins by itself) and never over SSH or without a seat, whatever the section says, and unblocks it after.
- **Temporary packages** (`omarchy_m_test/packages.py`): `packages.temporary(ctx, names, purpose)` leaves installed packages alone, works out exactly what installing the rest brings in (`pacman -Sp --needed`, never `-Sy`), refuses kernel, firmware and boot packages, shows the list and asks. With consent it uses sudo's cached credentials or `sudo -v` at the terminal, registers `sudo -n pacman -R` for exactly that list, installs with `--asdeps`, then narrows the restorer to what pacman actually installed.
- **Never** (`omarchy_m_test/safety.py`): every run goes through a guarded host that refuses to reboot or power off, to touch disk encryption, boot files, the boot loader or disks, to upgrade the system, or to install or remove kernel, firmware and boot packages, whatever a check asks (exit 126, and the reason). The Seam A tests assert it, and that whole runs never send such a command.

## The look

At a terminal the run looks like Omarchy's installer (`omarchy_m_test/theme.py`, `ui.py`): the screen cleared, the installed `logo.txt` (`$OMARCHY_PATH`, `/usr/share/omarchy` or `~/.local/share/omarchy`) centred in the current theme's green, section titles drawn by `omarchy-ascii` in the logo's font, the theme's colours from `~/.local/state/omarchy/current/theme/colors.toml` (resolved by `omarchy-theme-color`; older installs: `~/.config/omarchy/current/theme/`), gum prompts with the installer's styling unless the user sets their own `GUM_*`, and during a section a live feed of the last lines of what it runs, in grey, prefixed `  → `. Without Omarchy's files (another Asahi distro) it uses Tokyo Night and a plain title. Off a terminal (a pipe, the tests unless they give one) the output is plain text with no escape sequences.

## The host boundary

Every interaction with the machine, the human and the network goes through a `Host` (`omarchy_m_test/host.py`): run a command, read a file, list a directory, read an environment variable, prompt, show, run an interactive command (gum) on the terminal, ask for the terminal's size, write and remove files, post the report, GET the latest version. `scripts/check_boundary.py` fails CI if any other module does I/O or imports outside the standard library.

Tests replace the real host with a `RecordedHost` (`omarchy_m_test/recording.py`) that replays a recording from `tests/recordings/` and scripted answers. Anything the CLI asks for that isn't recorded raises `RecordingMiss`.

## Privacy

Every report passes `omarchy_m_test/privacy.py` before it is written, shown or uploaded: only the allowlisted fields (the same tree as `schema/report-v1.schema.json`) reach it, and every evidence line is scrubbed of MAC and IP addresses, Wi-Fi network names, home paths, hostnames, usernames, e-mail addresses, serial numbers, UUIDs and long hex identifiers. Evidence is text only and at most 64 KiB per report; the site refuses reports that break either rule.

## Machine key

On its first run the CLI creates an ed25519 key for this Mac at `$XDG_STATE_HOME/omarchy-m-test/machine-key` (`~/.local/state/...`; 0600, in a 0700 directory) with `ssh-keygen`, asking nothing, and reuses it on every later run. Every report carries its public key and a signature (`ssh-keygen -Y sign`, namespace `omarchy-m-test-report`) over its canonical form: the report without `signature`, as JSON with keys sorted, no whitespace and non-ASCII as UTF-8 (`omarchy_m_test/signing.py`). The private key never leaves the Mac, and record mode never records the key. The site refuses unsigned or tampered reports, groups reports by a keyed digest of the public key and never shows or exports the key. Without `ssh-keygen` the report is written unsigned and the run says the site won't take it.

## Recording a Mac

    bin/omarchy-m-test --dry-run --record my-mac.json

Record mode runs as usual and also saves what the Mac answered at the host boundary: every command, file and directory the CLI read, plus the sources later checks need (`RECORDED_SOURCES` in `recording.py`: kernel log, device tree, first-boot, Wi-Fi and lid journals, uname, PCI, input devices, addresses). The recording is scrubbed before it is saved. Prompts, answers, uploads and the machine key are not recorded. Check a new recording by eye before committing it, then add it to `tests/recordings/`.

`tests/corpus/` holds the real M1 and M2 evidence the seeded recordings came from, pseudonymized (every identifier swapped for a same-shape decoy) because this repository is public. The inventory answers (device-tree properties, bound drivers, `/proc/config.gz`) weren't captured either: they are reconstructed from each Mac's booted kernel package (its DTB, module aliases and headers' build config) and, for the M2, its kernel log's failed probe; the M1 has no kernel log at all. Answers never captured on a Mac (most of the M1's, and the M2's mac-check output) are reconstructed from what is known of the install and say so in their `note`; the v0.1 dogfood run replaces them. `scripts/reseed_recordings.py` reruns record mode over the corpus and rewrites `tests/recordings/` and the golden reports.

## Test (Seam A)

    python3 scripts/check_boundary.py
    python3 -m unittest discover -s tests -t .

The corpus tests run the whole CLI in record mode against the real evidence and fail if any identifier listed in a corpus machine's `forbidden`, or any MAC, IP, UUID, long hex id or home path, reaches a recording or a report. Reports produced here must equal the golden reports in `../schema/golden/`, which the site's Seam B tests post to the API.
