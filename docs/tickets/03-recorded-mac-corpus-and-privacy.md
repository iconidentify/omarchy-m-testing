# 03: Recorded-Mac corpus and privacy scrubber

**What to build:** A developer can record what a real Mac answers at the host boundary and replay it in tests, and every report is provably free of personal identifiers. The corpus starts from the M2 Max image-2 evidence already gathered (first-boot failure, green-frame capture, lid-sleep logs, 5 GHz first-join logs) and the M1 Pro on mx-mac.

**Blocked by:** 01

**Status:** ready-for-agent

Parent spec: maralcbr/omarchy-m-testing#1

- [x] A record mode captures host-boundary responses into a replayable recording, scrubbed before it is saved
- [x] Recordings seeded from existing M2 and M1 evidence and replayable in the Seam A tests
- [x] Allowlist privacy model: only permitted fields reach the report; evidence lines pass a scrubber for MAC addresses, IP addresses, Wi-Fi network names, home paths, hostnames, usernames and long hex identifiers
- [x] Evidence limited to text and at most 64 KiB per report
- [x] A zero-leak test runs the scrubber over real M1/M2 kernel logs and device-tree dumps and fails on any forbidden identifier
