# 18: Power

**What to build:** The tool measures idle power draw, checks the battery charge limit can be set and cleared (restoring the user's setting), and optionally measures battery drain over a ten-minute sleep.

**Blocked by:** 11, 15

**Status:** ready-for-agent

Parent spec: maralcbr/omarchy-m-testing#1

- [x] Idle power draw over 30 seconds
- [x] Charge limit set and cleared, original value restored
- [x] Optional sleep-drain test using the sleep section's resume support
- [x] Seam A tests with recordings
