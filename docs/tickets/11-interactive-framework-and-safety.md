# 11: Interactive framework and safety

**What to build:** Runs include guided human checks (yes, no or skip, with an optional note), and the tool can safely do things that change the machine: change the volume, drop and rejoin Wi-Fi, install test-only packages with consent and remove them afterwards. Sections that could cut the user's connection or session are skipped automatically over SSH or without a local desktop session.

**Blocked by:** 07

**Status:** ready-for-agent

Parent spec: maralcbr/omarchy-m-testing#1

- [ ] Human check type with yes/no/skip and optional note, recorded in the report
- [ ] Detection of SSH sessions and missing local seat; disruptive sections skipped with a clear reason
- [ ] Restorers for volume, Wi-Fi state and temporary packages, registered before each change
- [ ] Temporary test packages installed only after consent and removed at the end
- [ ] The tool never reboots and never touches disk encryption or boot files (asserted in tests)
- [ ] Seam A tests: human answers scripted; interruption mid-section restores everything
