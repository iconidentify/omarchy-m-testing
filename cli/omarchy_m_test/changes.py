"""Changes a section makes to the machine, each with its restorer registered first.

Volume (set_volume): the default sink is resolved to its PipeWire node id
once, so a sink that changes mid-section (headphones plugged in) isn't the
one put back. Its volume and mute are read, the restorers registered, then
the volume set and the sink unmuted. The level is capped at MAX_VOLUME (30%):
sound is never played louder, whatever a check asks for.

Wi-Fi (drop_wifi): Wi-Fi is soft-blocked with rfkill and unblocked by the
restorer. It is only dropped when there's a rejoin path: every Wi-Fi radio is
unblocked now and a Wi-Fi interface is connected (operstate up), so the
network is a known one iwd or NetworkManager rejoins by itself once the
radio is back. Never over SSH or without a local seat (presence.py), even if
the section forgot to say it's disruptive. rfkill works for the user at the
local seat (systemd gives them /dev/rfkill), so no sudo is needed.

Each helper returns a reason when it didn't make the change, for the check's
evidence; None when it did.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import presence
from .session import Context

SINK = "@DEFAULT_AUDIO_SINK@"
MAX_VOLUME = 0.30
NET = "/sys/class/net"
RFKILL_STATE = ["rfkill", "--noheadings", "--raw", "--output", "TYPE,SOFT,HARD"]
WIFI_OFF = ["rfkill", "block", "wlan"]
WIFI_ON = ["rfkill", "unblock", "wlan"]

_VOLUME = re.compile(r"^Volume:\s+([0-9]+(?:\.[0-9]+)?)(\s+\[MUTED\])?\s*$")
_NODE = re.compile(r"^id\s+([0-9]+),")


@dataclass(frozen=True)
class Volume:
    node: str
    level: str   # as wpctl printed it, e.g. "0.45"
    muted: bool


def read_volume(ctx: Context) -> Volume | None:
    """The default sink's node id, volume and mute; None without a default sink."""
    inspected = ctx.host.run(["wpctl", "inspect", SINK])
    node = _NODE.match(inspected.stdout.strip().splitlines()[0]) if inspected.returncode == 0 and inspected.stdout.strip() else None
    if node is None:
        return None
    current = ctx.host.run(["wpctl", "get-volume", node.group(1)])
    found = _VOLUME.match(current.stdout.strip()) if current.returncode == 0 else None
    if found is None:
        return None
    return Volume(node.group(1), found.group(1), bool(found.group(2)))


def set_volume(ctx: Context, level: float) -> str | None:
    """Set the default sink to `level` (0-1, capped at 30%) and unmute it; both are put back when the section ends."""
    level = max(0.0, min(level, MAX_VOLUME))
    before = read_volume(ctx)
    if before is None:
        return "no default audio output (wpctl found no sink)"
    ctx.change("the speaker volume", ["wpctl", "set-volume", before.node, f"{level:.2f}"], ["wpctl", "set-volume", before.node, before.level])
    if before.muted:
        ctx.change("the speaker mute", ["wpctl", "set-mute", before.node, "0"], ["wpctl", "set-mute", before.node, "1"])
    return None


def wifi_connected(ctx: Context) -> bool:
    """A Wi-Fi interface is associated with a network right now."""
    try:
        names = ctx.host.list_dir(NET)
    except OSError:
        return False
    for name in names:
        try:
            if "wireless" not in ctx.host.list_dir(f"{NET}/{name}"):
                continue
            if ctx.host.read_file(f"{NET}/{name}/operstate").decode("ascii", "replace").strip() == "up":
                return True
        except OSError:
            continue
    return False


def drop_wifi(ctx: Context) -> str | None:
    """Turn Wi-Fi off; it's turned back on (and rejoins) when the section ends."""
    blocked = presence.of(ctx.host, ctx.cache).blocks()
    if blocked:
        return blocked
    state = ctx.host.run(RFKILL_STATE)
    if state.returncode != 0:
        return "rfkill can't read the radios"
    radios = [line.split() for line in state.stdout.splitlines() if line.split()[:1] == ["wlan"]]
    if not radios:
        return "no Wi-Fi radio"
    if any(radio[1:3] != ["unblocked", "unblocked"] for radio in radios):
        return "Wi-Fi is already off"
    if not wifi_connected(ctx):
        return "Wi-Fi isn't connected, so there's no network to rejoin"
    result = ctx.change("Wi-Fi (turned back on to rejoin its network)", WIFI_OFF, WIFI_ON)
    if result.returncode != 0:
        return f"rfkill couldn't turn Wi-Fi off ({(result.stderr or result.stdout).strip() or result.returncode})"
    return None
