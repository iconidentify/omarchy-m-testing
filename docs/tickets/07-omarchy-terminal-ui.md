# 07: Omarchy-vibes terminal UI

**What to build:** A run looks and feels like Omarchy: the Omarchy logo in green, section titles in Omarchy's logo font, the user's current theme colours, gum prompts, and an installer-style live log during automatic checks. Sections can be skipped, a run resumes after an interruption, and every change the tool makes is undone at the end or on interruption. Other Asahi distros get a Tokyo Night fallback.

**Blocked by:** 01

**Status:** ready-for-agent

Parent spec: maralcbr/omarchy-m-testing#1

- [x] Uses the installed Omarchy logo, logo font, theme colours and gum styling when present; Tokyo Night fallback otherwise
- [x] Installer-style live progress feed during automatic checks
- [x] Sections listed up front; any section can be skipped
- [x] Checkpointing: an interrupted run resumes where it stopped
- [x] Restorer registry: every registered change is undone on normal exit, error or interrupt (tested by simulated interruption at Seam A)
