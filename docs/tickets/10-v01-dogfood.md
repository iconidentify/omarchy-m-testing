# 10: v0.1 dogfood on the M1 and M2

**What to build:** The v0.1 CLI runs for real on the M1 Pro and M2 Max against the live site: reports upload, pages show them, the gap map lists real unsupported hardware, and each run is saved as a new recording. Problems found are fixed or filed. Only after this is v0.1 announced.

**Blocked by:** 02, 04, 06, 07, 08, 09

**Status:** ready-for-agent (waits until the convergence work isn't using the M1 and M2)

Parent spec: maralcbr/omarchy-m-testing#1

- [ ] Full automatic run on each Mac, uploaded to production, report pages checked
- [ ] Each run saved as a scrubbed recording in the corpus; the zero-leak test passes on them
- [ ] Every problem found fixed or filed as a ticket
- [ ] Owner approves announcing v0.1

## Notes

- Candidate-set tag (from 06): the CLI reads `candidate_set=` from the image's target record (`/var/lib/omarchy/image/target`, or `target.booted` after first boot), else from `/var/lib/omarchy/factory-sealed`. The image builder (omarchy-mac-installer `image-builder/bin/build-mac-image`) writes the set only into `@factory`'s seal, so a freshly installed candidate image carries no tag. Before dogfooding a candidate image, file this with the installer: add `candidate_set=` to `write_image_target` (the target format ignores unknown keys).
- Reconstructed corpus answers (from 06): the M2's mac-check output and most of the M1's package, encryption, first-boot, mac-check, GPU, battery and CPU answers were never captured. Each carries a `note` in `cli/tests/corpus/*/host.json`. Replace them with this ticket's real recordings, then run `cli/scripts/reseed_recordings.py`.
