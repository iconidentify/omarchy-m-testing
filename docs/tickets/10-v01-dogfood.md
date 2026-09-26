# 10: v0.1 dogfood on the M1 and M2

**What to build:** The v0.1 CLI runs for real on the M1 Pro and M2 Max against the live site: reports upload, pages show them, the gap map lists real unsupported hardware, and each run is saved as a new recording. Problems found are fixed or filed. Only after this is v0.1 announced.

**Blocked by:** 02, 04, 06, 07, 08, 09

**Status:** ready-for-agent (waits until the convergence work isn't using the M1 and M2)

Parent spec: maralcbr/omarchy-m-testing#1

- [ ] Full automatic run on each Mac, uploaded to production, report pages checked
- [ ] Each run saved as a scrubbed recording in the corpus; the zero-leak test passes on them
- [ ] Every problem found fixed or filed as a ticket
- [ ] Owner approves announcing v0.1
