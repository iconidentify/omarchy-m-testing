# 13: On-screen video check

**What to build:** The tool plays a known test card on the built-in screen with hardware decode and checks the result automatically: it samples known regions of a screenshot for the expected colours and reads from the player's log whether hardware decode was actually used. This catches problems like the green, blocky frames seen on the M2, without claiming anything about tearing or refresh-rate correctness.

**Blocked by:** 11

**Status:** ready-for-agent

Parent spec: maralcbr/omarchy-m-testing#1

- [x] Known test card generated or bundled; played for H.264 and HEVC with hardware decode
- [x] Screenshot sampled in known regions for expected colours (standard-library PNG decoding)
- [x] Hardware decode confirmed from the player log; mode recorded
- [x] Seam A tests with the recorded green-frame capture (fails) and a correct capture (passes)
