"""The disclaimer. Bump CONSENT_VERSION whenever its meaning changes."""

CONSENT_VERSION = 5

DISCLAIMER = """\
omarchy-m-test checks how well Omarchy supports this Mac's hardware.

What it does:
  - Reads facts about this Mac (model, chip, kernel) and runs checks.
  - Asks you to look, listen or do something for some checks: answer yes,
    no or skip, with a note if you like. Skipping never counts as a failure.
  - Changes a few things for a check and puts them back when the check ends,
    even if the run is interrupted: the volume (never above 30%), Wi-Fi
    (dropped and rejoined; never over SSH), the battery charge limit (set
    to 80% and cleared, then put back as you had it), and temporary test
    packages (installed without asking again, shown as they're installed,
    never a kernel, firmware or boot package and never an upgrade; only
    the ones it installed are removed when their section ends).
  - Writes a report file and shows you the exact report.
  - Uploads the report only if you say yes after seeing it (never with --dry-run).

What it never does:
  - Reboot your Mac, or touch disk encryption or boot files.
  - Put your Mac to sleep by itself: only you do, by closing the lid when
    it asks (never over SSH).
  - Collect serial numbers, MAC or IP addresses, hostnames, usernames,
    Wi-Fi network names, disk identifiers or anything in your home directory.
"""

ACCEPT_PROMPT = "Accept and start? [Y/n] "


def accepted(answer: str) -> bool:
    """Enter (the default) or y accepts; anything else cancels."""
    return answer.strip().lower() in ("", "y", "yes")
