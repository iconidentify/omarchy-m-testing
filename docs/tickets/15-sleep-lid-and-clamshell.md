# 15: Sleep, lid and clamshell

**What to build:** The user closes and opens the lid when prompted; the tool verifies suspend and resume, clamshell mode with a USB-C external display (built-in screen off, external on, no sleep), and whether Wi-Fi and Thunderbolt recover after resume. The run survives the suspend and continues where it was.

**Blocked by:** 11

**Status:** ready-for-agent

Parent spec: maralcbr/omarchy-m-testing#1

- [ ] Lid-close/open prompts; suspend and resume detected from the system log
- [ ] Clamshell with external display: no suspend, built-in off, external on
- [ ] Wi-Fi and Thunderbolt link state checked after resume
- [ ] Run resumes across the suspend via checkpoints
- [ ] Seam A tests with the recorded lid-sleep failure (suspend with USB-C display) and a good clamshell
