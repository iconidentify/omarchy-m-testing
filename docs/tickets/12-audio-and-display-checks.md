# 12: Audio and display checks

**What to build:** The user hears a short speaker tone (only after speaker protection is confirmed active, at no more than 30% volume), confirms the microphone and headphone detection, and checks the display: bar icons clear of the notch, brightness steps, the ambient light sensor driving the keyboard light, and a visible cursor.

**Blocked by:** 06, 11

**Status:** ready-for-agent

Parent spec: maralcbr/omarchy-m-testing#1

- [x] Speaker tone plays only when speaker protection is active; volume capped at 30% and restored
- [x] Microphone capture shows signal; headphone jack detection prompt
- [x] Notch-bar, brightness, ambient light/keyboard light and cursor checks with human confirmation where needed
- [x] Seam A tests with scripted answers, including speaker protection inactive (tone skipped)
