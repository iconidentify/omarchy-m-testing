# 06: Core automatic checks

**What to build:** A run covers every hardware area a machine can check on its own: boot chain and encryption, GPU driver and API support, audio routing and speaker protection, Wi-Fi and Bluetooth state, displays, snapshots, battery status and CPU frequency scaling. It reuses omarchy-mac's existing hardware check script rather than duplicating it, and detects which Omarchy stack (converged image, mx-mac, legacy omarchy-mac) or reference distro it's on.

**Blocked by:** 03, 05

**Status:** ready-for-agent

Parent spec: maralcbr/omarchy-m-testing#1

- [x] Wraps omarchy-mac's hardware check script and turns its PASS/FAIL/SKIP lines into catalogue-classified results; root-only checks run via passwordless sudo when available and are skipped cleanly otherwise
- [x] Boot and encryption, GPU, audio, network state, displays, snapshots, battery and CPU scaling checks implemented as automatic checks
- [x] Stack detection: the three Omarchy stacks plus reference distros, recorded in the report
- [x] Candidate-set tag recorded when the image's target record is present
- [x] Seam A tests with M1 and M2 recordings, including known failures (offline first-boot hardware setup, missing packages), produce the expected results
