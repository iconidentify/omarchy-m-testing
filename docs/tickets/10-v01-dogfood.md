# 10: v0.1 dogfood on the M1 and M2

**What to build:** The v0.1 CLI runs for real on the M1 Pro and M2 Max against the live site: reports upload, pages show them, the gap map lists real unsupported hardware, and each run is saved as a new recording. Problems found are fixed or filed. Only after this is v0.1 announced.

**Blocked by:** 02, 04, 06, 07, 08, 09

**Status:** ready-for-agent (waits until the convergence work isn't using the M1 and M2)

Parent spec: maralcbr/omarchy-m-testing#1

- [ ] Full automatic run on each Mac, uploaded to production, report pages checked
  - [x] M1 Pro (0.1.2, over SSH: https://omarchy-m-testing.org/reports/ehkyUxczpv9z754mdpbL1Yer; report, matrix and gaps pages checked)
  - [ ] M2 Max
- [ ] Each run saved as a scrubbed recording in the corpus; the zero-leak test passes on them
  - [x] M1 Pro (`cli/tests/corpus/m1-pro-converged`, `cli/tests/recordings/m1-pro-converged.json`)
  - [ ] M2 Max
- [ ] Every problem found fixed or filed as a ticket
  - [x] M1 Pro (fixed in this PR, the rest filed under "M1 dogfood findings" below)
  - [ ] M2 Max
- [ ] Owner approves announcing v0.1

## Notes

- Candidate-set tag (from 06): the CLI reads `candidate_set=` from the image's target record (`/var/lib/omarchy/image/target`, or `target.booted` after first boot), else from `/var/lib/omarchy/factory-sealed`. The image builder (omarchy-mac-installer `image-builder/bin/build-mac-image`) writes the set only into `@factory`'s seal, so a freshly installed candidate image carries no tag. Before dogfooding a candidate image, file this with the installer: add `candidate_set=` to `write_image_target` (the target format ignores unknown keys).
- Reconstructed corpus answers (from 06): the M2's mac-check output and most of the M1's package, encryption, first-boot, mac-check, GPU, battery and CPU answers were never captured. Each carries a `note` in `cli/tests/corpus/*/host.json`. Replace them with this ticket's real recordings, then run `cli/scripts/reseed_recordings.py`.

## M1 dogfood findings (2026-09-27, Brisbane)

The M1 Pro runs the converged image after the mx-mac migration (omarchy 4.0.0 quattro, omarchy-mac 0.1.0, linux-aurora 7.1.12.aurora2-10, Limine, LUKS root). Releases 0.1.1 and 0.1.2 were cut from main; `curl -fsSL https://omarchy-m-testing.org/install | bash` installed and then upgraded it. Both runs went over SSH with nobody at the Mac: every human question was answered skip (with a note saying so), the video and Wi-Fi first-join checks skipped as designed. 0.1.2 report: 31 pass, 5 fail, 11 skip. An earlier 0.1.1 upload (https://omarchy-m-testing.org/reports/uUbp4i2HJTALyMQ9v5EddCHx) was checked for device names, aliases, the pretty hostname, hex dumps and e-mail addresses: none, so it stays.

Fixed in this PR:
- `hardware.drivers` listed the three CPU frequency clusters, the architected timer and U-Boot's SMBIOS node as unclaimed (so the gap map showed them as unknown hardware, and CPU frequency scaling as failing, while `cpu.frequency-scaling` passed). No driver binds these by design, so they're counted as that and not listed as unclaimed. The M2's corpus never showed it because its uevents are reconstructed: its real run will.
- Over SSH brightnessctl may not set the backlight at all. The brightness check was skipped correctly, but the section end then printed "Couldn't undo: the screen brightness" with a command to run by hand, though nothing had changed. Now, when not even the first step takes, nothing is left to put back.

Real results, not tool bugs (for omarchy-mac):
- `omarchy-asahi-mic.service` and `omarchy-brightness-keyboard-auto.service` (user units, preset enabled) are disabled on the migrated M1, so `audio.microphone-mapping` and `input.auto-keyboard-light` fail. The mx-mac to converged migration seems not to run `systemctl --user preset` for these units (a fresh image enables them).
- The AVD's firmware (`apple/avd-fw-v3-t0.bin`) is missing, so the video decoder fails to probe (`hardware.firmware`, `hardware.probe-errors`), as on the M2 Max.
- `cpuinfo_max_freq` of the P-clusters is 3036000 on linux-aurora (the mx-mac corpus has 3228000 from linux-asahi); `boost` is present, so the top state is probably behind boost. Worth a look, not a failure.

Filed (not fixed here):
- Over-scrubbing: the scrubber learns every saved NetworkManager connection name (`nmcli --get-values NAME connection show`) as a Wi-Fi network, so the M1's `docker0` bridge and `tailscale0` tunnel become `<ssid>` everywhere (kernel log, `ip -brief address`). No leak, but it garbles evidence. Learn only `802-11-wireless` connections (`nmcli -t -f NAME,TYPE`), which changes a recorded command, so all three corpora need reseeding.
- Record mode's device-tree dump fails on the M1's converged device tree (`dtc`: `ERROR (node_name_not_empty): /reserved-memory/@103d2310000: Empty node name`), so the recording has no DTS. `dtc -f` would force it; changing the recorded argv means reseeding the M2 corpus too.
- `vulkaninfo --summary` version numbers such as `1.4.x.y` are scrubbed as `<ip>`. Harmless, a bit ugly.
- Over SSH the Audio section still measures the microphone and plays the 30% tone (it isn't disruptive by design); on an unattended run nobody hears it. Consider skipping the tone when the run is remote, as the video check does.
- `/gaps` shows "Unknown hardware: None reported" above an unclaimed-hardware table listing unknown hardware (from the 0.1.1/0.1.2 reports' false entries): the two sections count different things. Once this PR is released and the M1 re-run, those entries go; the wording could still say the top list is per feature.
- The report page and matrix show 1 machine; the matrix only sets a cell's state once 2 machines agree, so every M1 cell is still tentative until another M1 Pro reports.
