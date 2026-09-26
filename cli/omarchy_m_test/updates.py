"""Tell the user, before a run, when a newer release of the tool exists.

Every tagged release publishes its version as a VERSION asset, so the latest
release's version is one small GET. Any failure (offline, GitHub down, an
odd answer) stays silent: the check must never stop or slow a run.
"""

from __future__ import annotations

import re

from . import TOOL_NAME, TOOL_VERSION
from .host import Host, NetworkError

RELEASES = "https://github.com/maralcbr/omarchy-m-testing/releases"
LATEST_VERSION_URL = RELEASES + "/latest/download/VERSION"
INSTALL_COMMAND = "curl -fsSL https://omarchy-m-testing.org/install | bash"

_VERSION = re.compile(r"\A(\d+)\.(\d+)\.(\d+)\Z")


def _parse(version: str) -> tuple[int, int, int] | None:
    match = _VERSION.match(version.strip().removeprefix("v"))
    return tuple(int(part) for part in match.groups()) if match else None  # type: ignore[return-value]


def newer_release(host: Host, current: str = TOOL_VERSION) -> str | None:
    """The latest release's version when it is newer than `current`, else None."""
    try:
        response = host.get(LATEST_VERSION_URL)
    except NetworkError:
        return None
    if response.status != 200:
        return None
    latest, mine = _parse(response.body), _parse(current)
    if latest is None or mine is None or latest <= mine:
        return None
    return ".".join(str(part) for part in latest)


def notify(host: Host) -> None:
    latest = newer_release(host)
    if latest:
        host.show(
            f"A newer {TOOL_NAME} is available: {latest} (this is {TOOL_VERSION}). "
            f"Results are best with the latest checks; update with:\n  {INSTALL_COMMAND}\n"
        )
