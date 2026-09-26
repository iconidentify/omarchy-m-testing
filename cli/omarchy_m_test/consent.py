"""The disclaimer. Bump CONSENT_VERSION whenever its meaning changes."""

CONSENT_VERSION = 1

DISCLAIMER = """\
omarchy-m-test checks how well Omarchy supports this Mac's hardware.

What it does:
  - Reads facts about this Mac (model, chip, kernel) and runs checks.
  - Writes a report file and shows you the exact report.
  - Uploads the report only if you say yes after seeing it (never with --dry-run).

What it never does:
  - Reboot your Mac, or touch disk encryption or boot files.
  - Collect serial numbers, MAC or IP addresses, hostnames, usernames,
    Wi-Fi network names, disk identifiers or anything in your home directory.
"""

ACCEPT_PROMPT = "Press Enter to accept and start, or type anything else to cancel: "


def accepted(answer: str) -> bool:
    """Only a bare Enter accepts."""
    return answer == ""
