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

Wi-Fi driver (wifi_link, reload_wifi_driver): the Broadcom driver is
unloaded and loaded again (`sudo -n modprobe -r brcmfmac_wcc brcmfmac`, then
`sudo -n modprobe brcmfmac`), as a boot or omarchy-mac's resume recovery
starts it. Only with a rejoin path: presence allows it (never over SSH, so
never over an SSH session carried by this Wi-Fi, and only at a local seat),
the interface is brcmfmac's and associated, and NetworkManager has it
activated on a saved connection set to connect automatically, so
NetworkManager joins that network again by itself once the driver is back.
Two restorers are registered before the driver is unloaded: load the driver
(a no-op when it's loaded) and, after it, bring the original connection back
up if it isn't activated (`nmcli connection up UUID`). The connection is
known by its UUID only; its network name is never read.

Each helper returns a reason when it didn't make the change, for the check's
evidence; None when it did.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import packages, presence
from .session import Context

SINK = "@DEFAULT_AUDIO_SINK@"
MAX_VOLUME = 0.30
NET = "/sys/class/net"
RFKILL_STATE = ["rfkill", "--noheadings", "--raw", "--output", "TYPE,SOFT,HARD"]
WIFI_OFF = ["rfkill", "block", "wlan"]
WIFI_ON = ["rfkill", "unblock", "wlan"]
WIFI_DRIVER = "brcmfmac"
WIFI_DRIVER_MODULES = ("brcmfmac_wcc", "brcmfmac")  # unloaded in this order; brcmfmac_wcc only when loaded
LOAD_WIFI_DRIVER = ["sudo", "-n", "modprobe", WIFI_DRIVER]
# Run as `sh -c SCRIPT sh INTERFACE`: prints the associated channel's frequency in MHz, nothing else (no network name).
FREQUENCY_SCRIPT = 'iw dev "$1" link 2>/dev/null | awk \'/freq:/ { print int($2); exit }\''
# Run as `sh -c SCRIPT sh INTERFACE`: how many IPv4 addresses (not link-local) the interface has; never the addresses.
ADDRESSES_SCRIPT = 'ip -4 -o address show dev "$1" 2>/dev/null | grep -v " inet 169\\.254\\." | grep -c " inet "'
# Run as `sh -c SCRIPT sh UUID`: brings the connection up unless it's activated already.
RECONNECT_SCRIPT = '[ "$(nmcli -g GENERAL.STATE connection show "$1" 2>/dev/null)" = activated ] || nmcli --wait 45 connection up "$1"'

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
    changed = ctx.change("the speaker volume", ["wpctl", "set-volume", before.node, f"{level:.2f}"], ["wpctl", "set-volume", before.node, before.level])
    if changed.returncode != 0:
        return f"wpctl couldn't set the volume ({(changed.stderr or changed.stdout).strip() or changed.returncode})"
    if before.muted:
        unmuted = ctx.change("the speaker mute", ["wpctl", "set-mute", before.node, "0"], ["wpctl", "set-mute", before.node, "1"])
        if unmuted.returncode != 0:
            return f"wpctl couldn't unmute the speaker ({(unmuted.stderr or unmuted.stdout).strip() or unmuted.returncode})"
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


@dataclass(frozen=True)
class WifiLink:
    """The Wi-Fi connection a driver reload has to come back to."""

    interface: str
    connection: str  # NetworkManager's UUID for it: never reported
    frequency: int | None  # MHz, None if iw couldn't say


def frequency_argv(interface: str) -> list[str]:
    return ["sh", "-c", FREQUENCY_SCRIPT, "sh", interface]


def addresses_argv(interface: str) -> list[str]:
    return ["sh", "-c", ADDRESSES_SCRIPT, "sh", interface]


def reconnect_argv(connection: str) -> list[str]:
    return ["sh", "-c", RECONNECT_SCRIPT, "sh", connection]


def unload_wifi_driver_argv(modules: list[str]) -> list[str]:
    return ["sudo", "-n", "modprobe", "-r", *modules]


def _driver(ctx: Context, interface: str) -> str | None:
    try:
        uevent = ctx.host.read_file(f"{NET}/{interface}/device/uevent").decode("ascii", "replace")
    except OSError:
        return None
    return next((line.partition("=")[2].strip() for line in uevent.splitlines() if line.startswith("DRIVER=")), None)


def wifi_link(ctx: Context) -> tuple[str | None, WifiLink | None]:
    """The rejoin path for a Wi-Fi driver reload: (why there's none, or None; the link to come back to)."""
    blocked = presence.of(ctx.host, ctx.cache).blocks()
    if blocked:
        return blocked, None
    try:
        names = ctx.host.list_dir(NET)
    except OSError:
        return "no network interfaces to look at", None
    interface = None
    for name in names:
        try:
            if "wireless" in ctx.host.list_dir(f"{NET}/{name}") and _driver(ctx, name) == WIFI_DRIVER:
                interface = name
                break
        except OSError:
            continue
    if interface is None:
        return f"no Wi-Fi interface driven by {WIFI_DRIVER} (the Mac's Broadcom Wi-Fi)", None
    if not wifi_connected(ctx):
        return "Wi-Fi isn't connected, so there's no network to rejoin", None

    device = ctx.host.run(["nmcli", "-g", "GENERAL.STATE,GENERAL.CON-UUID", "device", "show", interface])
    if device.returncode != 0:
        return "NetworkManager doesn't manage the Wi-Fi, so nothing would rejoin the network", None
    lines = device.stdout.strip().splitlines()
    if len(lines) != 2 or not lines[0].startswith("100 ") or not lines[1].strip():
        return "NetworkManager hasn't activated a Wi-Fi connection, so nothing would rejoin the network", None
    connection = lines[1].strip()
    autoconnect = ctx.host.run(["nmcli", "-g", "connection.autoconnect", "connection", "show", connection])
    if autoconnect.returncode != 0 or autoconnect.stdout.strip() != "yes":
        return "the Wi-Fi connection isn't set to connect automatically, so nothing would rejoin it", None
    addresses = ctx.host.run(addresses_argv(interface)).stdout.strip()
    if not addresses.isdigit() or int(addresses) == 0:
        return "Wi-Fi has no IPv4 address now, so there's nothing to compare a rejoin with", None
    found = ctx.host.run(frequency_argv(interface)).stdout.strip()
    return None, WifiLink(interface, connection, int(found) if found.isdigit() else None)


def reload_wifi_driver(ctx: Context, link: WifiLink) -> tuple[str | None, bool]:
    """Unload and load the Wi-Fi driver; the driver and the connection are put back when the section ends.

    Returns (why it wasn't reloaded, or None; whether the driver was unloaded and wouldn't load again).
    """
    blocked = presence.of(ctx.host, ctx.cache).blocks()
    if blocked:
        return blocked, False
    if not packages.sudo_ready(ctx):
        return "reloading the Wi-Fi driver needs sudo, and it wasn't given", False
    modules = []
    for module in WIFI_DRIVER_MODULES:
        try:
            ctx.host.list_dir(f"/sys/module/{module}")
            modules.append(module)
        except OSError:
            continue
    if WIFI_DRIVER not in modules:
        return f"{WIFI_DRIVER} isn't loaded as a module, so it can't be reloaded", False
    ctx.changes.register("the Wi-Fi connection (brought back up if it isn't)", reconnect_argv(link.connection))
    ctx.changes.register("the Wi-Fi driver (loaded again)", LOAD_WIFI_DRIVER, sudo=True)
    unloaded = ctx.host.run(unload_wifi_driver_argv(modules))
    if unloaded.returncode != 0:
        return f"modprobe couldn't unload the Wi-Fi driver ({(unloaded.stderr or unloaded.stdout).strip() or unloaded.returncode})", False
    ctx.host.run(["sleep", "1"])
    loaded = ctx.host.run(LOAD_WIFI_DRIVER)
    if loaded.returncode != 0:
        return f"modprobe couldn't load the Wi-Fi driver again ({(loaded.stderr or loaded.stdout).strip() or loaded.returncode})", True
    return None, False
