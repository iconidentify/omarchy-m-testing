"""The Ports section: USB-C, Thunderbolt/USB4 and external displays on USB-C, then the human's word on them.

At the Mac (a local seat, no SSH), the human is first asked to plug in what
they'd like checked. Then three small scripts on the Mac list what's there,
printing only kinds, roles, speeds and modes: never a device's name, vendor
string or serial (the scrubber would catch those, but they never leave the
script).

  - USB-C (automatic, usb3-tb-ports): the USB-C ports the USB-PD controller
    (tipd) registered in /sys/class/typec, whether something is plugged into
    each and the data and power roles, and the USB controllers (root hubs)
    and devices in /sys/bus/usb with their speed and class. It passes with
    at least one USB-C port and one USB controller.
  - Thunderbolt/USB4 (automatic, thunderbolt): the domains Aurora's
    thunderbolt-apple-nhi registered in /sys/bus/thunderbolt, and the
    devices and other computers linked to them (generation, speed, lanes,
    whether the device is authorized). It passes with at least one domain.
  - External displays (automatic, usb4-displays): the DRM connectors on
    USB-C (connector type USB: card2-USB-2 is Hyprland's USB-2) from
    /sys/class/drm, connected or not, in use and their preferred mode. It
    passes when every connected one is in use; with none connected it is
    skipped; a Mac whose kernel has no USB-C connectors at all fails (no DP
    alt mode). HDMI is display.outputs' and only noted.
  - Devices work (human): with anything plugged in, does it all work?
  - External display picture (human): with a display on USB-C, is its
    picture right?
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import human, presence
from .session import Context
from .ui import Ui

USB_C = "ports.usb-c"
THUNDERBOLT = "ports.thunderbolt"
DISPLAYS = "ports.external-displays"
DEVICES_WORK = "ports.devices-work"
PICTURE = "ports.external-display-picture"
CHECK_IDS = (USB_C, THUNDERBOLT, DISPLAYS, DEVICES_WORK, PICTURE)

# Run as `sh -c SCRIPT`. "typec N partner=yes|no data=ROLE power=ROLE" per USB-C port, then
# "usb root|device speed=MBPS class=XX" per USB device (a device's own class, else its first interface's).
USB_SCRIPT = r"""for p in /sys/class/typec/port*; do
  n=${p##*/port}
  case $n in ''|*[!0-9]*) continue;; esac
  if [ -e "/sys/class/typec/port$n-partner" ]; then partner=yes; else partner=no; fi
  data=$(sed -n 's/.*\[\(.*\)\].*/\1/p' "$p/data_role" 2>/dev/null)
  power=$(sed -n 's/.*\[\(.*\)\].*/\1/p' "$p/power_role" 2>/dev/null)
  echo "typec $n partner=$partner data=$data power=$power"
done
for d in /sys/bus/usb/devices/*; do
  [ -r "$d/speed" ] || continue
  case ${d##*/} in *:*) continue;; usb*) kind=root;; *) kind=device;; esac
  class=$(cat "$d/bDeviceClass" 2>/dev/null)
  if [ "$class" = 00 ]; then class=$(cat "$d"/*:*/bInterfaceClass 2>/dev/null | head -n 1); fi
  echo "usb $kind speed=$(cat "$d/speed") class=$class"
done"""
USB = ["sh", "-c", USB_SCRIPT]

# "nobus" without the Thunderbolt bus, else "thunderbolt NAME DEVTYPE key=value..." per entry.
THUNDERBOLT_SCRIPT = r"""if [ ! -d /sys/bus/thunderbolt/devices ]; then echo nobus; exit 0; fi
for d in /sys/bus/thunderbolt/devices/*; do
  [ -r "$d/uevent" ] || continue
  line="thunderbolt ${d##*/} $(sed -n 's/^DEVTYPE=//p' "$d/uevent")"
  for f in generation rx_speed rx_lanes authorized; do
    if [ -r "$d/$f" ]; then line="$line $f=$(tr -d ' \n' < "$d/$f")"; fi
  done
  echo "$line"
done"""
THUNDERBOLT_LIST = ["sh", "-c", THUNDERBOLT_SCRIPT]

# "connector NAME STATUS ENABLED MODE" per DRM connector (MODE: the preferred one, when connected).
DISPLAYS_SCRIPT = r"""for c in /sys/class/drm/card*-*; do
  [ -r "$c/status" ] || continue
  echo "connector ${c##*/} $(cat "$c/status") $(cat "$c/enabled" 2>/dev/null) $(head -n 1 "$c/modes" 2>/dev/null)"
done"""
DISPLAYS_LIST = ["sh", "-c", DISPLAYS_SCRIPT]

USB_CLASSES = {
    "01": "audio", "02": "communications", "03": "input (HID)", "05": "physical", "06": "imaging", "07": "printer",
    "08": "storage", "09": "hub", "0a": "CDC data", "0b": "smart card", "0e": "video", "0f": "health", "10": "audio/video",
    "11": "billboard", "dc": "diagnostic", "e0": "wireless", "ef": "miscellaneous", "fe": "application", "ff": "vendor-specific",
}
USB_C_CONNECTORS = ("USB-", "DP-")

PLUG_IN = (
    "Plug in what you'd like checked on the USB-C ports: a USB stick or hub, a Thunderbolt or USB4 dock or device, "
    "a display over USB-C (or a USB-C to DisplayPort or HDMI adapter)."
)
READY = "Press Enter once they're in (or now, with nothing to plug in): "
DEVICES_QUESTION = (
    "Is everything you plugged into the USB-C ports listed above, and does it work "
    "(a stick's files open, a hub's or dock's ports work, a charger charges)?"
)
PICTURE_QUESTION = (
    "Look at the display on USB-C: is the picture sharp and steady at its full resolution, "
    "and does the pointer move onto it?"
)


@dataclass
class Usb:
    ports: list[tuple[str, bool, str, str]] = field(default_factory=list)  # (number, plugged in, data role, power role)
    roots: list[str] = field(default_factory=list)  # speeds
    devices: list[tuple[str, str]] = field(default_factory=list)  # (speed, class)


def parse_usb(stdout: str) -> Usb:
    usb = Usb()
    for line in stdout.splitlines():
        words = line.split()
        if not words:
            continue
        fields = dict(word.partition("=")[::2] for word in words[2:] if "=" in word)
        if words[0] == "typec" and len(words) >= 2 and words[1].isdigit():
            usb.ports.append((words[1], fields.get("partner") == "yes", fields.get("data", ""), fields.get("power", "")))
        elif words[0] == "usb" and len(words) >= 2 and words[1] in ("root", "device"):
            speed = fields.get("speed", "")
            if words[1] == "root":
                usb.roots.append(speed)
            else:
                usb.devices.append((speed, fields.get("class", "").lower()))
    return usb


def _speed(mbps: str) -> str:
    return f"{mbps} Mbps" if mbps else "unknown speed"


def usb_c(ctx: Context) -> tuple[dict, Usb]:
    usb = parse_usb(ctx.host.run(USB).stdout)
    evidence = []
    if usb.ports:
        plugged = [port for port in usb.ports if port[1]]
        evidence.append(f"USB-C ports: {len(usb.ports)} (USB-PD controller, /sys/class/typec), {len(plugged)} with something plugged in")
        for number, _, data, power in plugged:
            roles = ", ".join(role for role in (f"data {data}" if data else "", f"power {power}" if power else "") if role)
            evidence.append(f"port {number}: plugged in" + (f" ({roles})" if roles else ""))
    else:
        evidence.append("no USB-C ports registered (the USB-PD controller, tipd, didn't come up)")
    if usb.roots:
        speeds = sorted(set(usb.roots), key=lambda s: float(s) if _number(s) else 0)
        evidence.append(f"USB controllers: {len(usb.roots)} root hubs ({', '.join(_speed(s) for s in speeds)})")
    else:
        evidence.append("no USB controller (no root hub in /sys/bus/usb)")
    if usb.devices:
        evidence.append(f"USB devices: {len(usb.devices)}: " + ", ".join(
            f"{USB_CLASSES.get(cls, f'class {cls}' if cls else 'unknown class')} at {_speed(speed)}" for speed, cls in usb.devices))
    else:
        evidence.append("USB devices: none")
    status = "pass" if usb.ports and usb.roots else "fail"
    return _automatic(USB_C, status, evidence), usb


@dataclass
class Thunderbolt:
    bus: bool = True
    domains: list[str] = field(default_factory=list)
    devices: list[dict[str, str]] = field(default_factory=list)  # linked devices (not the host routers)
    hosts: list[dict[str, str]] = field(default_factory=list)  # other computers (XDomain links)
    retimers: int = 0


def parse_thunderbolt(stdout: str) -> Thunderbolt:
    found = Thunderbolt()
    for line in stdout.splitlines():
        words = line.split()
        if words == ["nobus"]:
            found.bus = False
        if len(words) < 3 or words[0] != "thunderbolt":
            continue
        name, kind = words[1], words[2]
        fields = dict(word.partition("=")[::2] for word in words[3:] if "=" in word)
        if kind == "thunderbolt_domain":
            found.domains.append(name)
        elif kind == "thunderbolt_xdomain":
            found.hosts.append(fields)
        elif kind == "thunderbolt_retimer":
            found.retimers += 1
        elif kind == "thunderbolt_device" and not re.fullmatch(r"\d+-0", name):
            found.devices.append(fields)
    return found


def _link(fields: dict[str, str]) -> str:
    parts = []
    if fields.get("generation"):
        parts.append(f"generation {fields['generation']}")
    if fields.get("rx_speed"):
        parts.append(fields["rx_speed"].replace("Gb/s", " Gb/s"))
    if fields.get("rx_lanes"):
        parts.append(f"{fields['rx_lanes']} lane{'s' if fields['rx_lanes'] != '1' else ''}")
    if fields.get("authorized") == "0":
        parts.append("not authorized")
    return f" ({', '.join(parts)})" if parts else ""


def thunderbolt(ctx: Context) -> tuple[dict, Thunderbolt]:
    found = parse_thunderbolt(ctx.host.run(THUNDERBOLT_LIST).stdout)
    if not found.domains:
        why = "no Thunderbolt bus in this kernel" if not found.bus else "no domain registered"
        return _automatic(THUNDERBOLT, "fail", [f"no Thunderbolt/USB4 controller: {why} (thunderbolt-apple-acio, thunderbolt-apple-nhi)"]), found
    evidence = [f"Thunderbolt/USB4 controllers: {len(found.domains)} (domains registered by thunderbolt-apple-nhi)"]
    for fields in found.devices:
        evidence.append("linked: a Thunderbolt or USB4 device" + _link(fields))
    for fields in found.hosts:
        evidence.append("linked: another computer, host-to-host" + _link(fields))
    if found.retimers:
        evidence.append(f"retimers: {found.retimers}")
    if not found.devices and not found.hosts:
        evidence.append("linked: nothing")
    return _automatic(THUNDERBOLT, "pass", evidence), found


@dataclass(frozen=True)
class Connector:
    name: str  # without the card: USB-2, as Hyprland names it
    connected: bool
    enabled: bool
    mode: str

    @property
    def usb_c(self) -> bool:
        return self.name.startswith(USB_C_CONNECTORS)


def parse_connectors(stdout: str) -> list[Connector]:
    found = []
    for line in stdout.splitlines():
        words = line.split()
        if len(words) < 3 or words[0] != "connector":
            continue
        name = re.sub(r"^card\d+-", "", words[1])
        mode = next((w for w in words[4:] if re.fullmatch(r"\d+x\d+\w*", w)), "")
        found.append(Connector(name, words[2] == "connected", len(words) > 3 and words[3] == "enabled", mode))
    return found


def displays(ctx: Context) -> tuple[dict, list[Connector]]:
    connectors = parse_connectors(ctx.host.run(DISPLAYS_LIST).stdout)
    usb_c = [c for c in connectors if c.usb_c]
    lit = [c for c in usb_c if c.connected and c.enabled]
    evidence = []
    if not usb_c:
        evidence.append("no display connectors on the USB-C ports (no DP alt mode in this kernel)")
    else:
        evidence.append(f"USB-C display connectors: {len(usb_c)} ({', '.join(c.name for c in usb_c)})")
    for c in usb_c:
        if c.connected:
            state = "in use" if c.enabled else "connected but not in use"
            evidence.append(f"{c.name}: {state}" + (f", {c.mode} preferred" if c.mode else ""))
    for c in connectors:
        if c.name.startswith("HDMI") and c.connected:
            evidence.append(f"{c.name}: connected (HDMI, not USB-C: see display.outputs)")
    if not usb_c:
        return _automatic(DISPLAYS, "fail", evidence), lit
    connected = [c for c in usb_c if c.connected]
    if not connected:
        return _automatic(DISPLAYS, "skip", [*evidence, "skipped: no display plugged into a USB-C port"]), lit
    return _automatic(DISPLAYS, "pass" if len(lit) == len(connected) else "fail", evidence), lit


def devices_work(ctx: Context, usb: Usb, links: Thunderbolt) -> dict:
    plugged = sum(1 for port in usb.ports if port[1])
    if not (plugged or usb.devices or links.devices or links.hosts):
        return human.skip(DEVICES_WORK, "nothing plugged into the USB-C ports")
    listed = (f"listed: {plugged} USB-C port(s) in use, {len(usb.devices)} USB device(s), "
              f"{len(links.devices) + len(links.hosts)} Thunderbolt/USB4 link(s)")
    return human.check(ctx, DEVICES_WORK, DEVICES_QUESTION, [listed])


def picture(ctx: Context, lit: list[Connector]) -> dict:
    if not lit:
        return human.skip(PICTURE, "no display in use on a USB-C port")
    shown = ", ".join(c.name + (f" at {c.mode}" if c.mode else "") for c in lit)
    return human.check(ctx, PICTURE, PICTURE_QUESTION, [f"display on USB-C: {shown}"])


def run(ctx: Context) -> list[dict]:
    if presence.of(ctx.host, ctx.cache).blocks() is None:
        ui = ctx.ui or Ui(ctx.host)
        ui.text(PLUG_IN)
        try:
            ui.ask(READY)
        except EOFError:
            pass
    usb_result, usb = usb_c(ctx)
    links_result, links = thunderbolt(ctx)
    displays_result, lit = displays(ctx)
    _say(ctx, "Found:\n  " + "\n  ".join([*usb_result["evidence"], *links_result["evidence"], *displays_result["evidence"]]))
    return [usb_result, links_result, displays_result, devices_work(ctx, usb, links), picture(ctx, lit)]


def _number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def _say(ctx: Context, text: str) -> None:
    if ctx.ui:
        ctx.ui.text(text)
    else:
        ctx.host.show(text)


def _automatic(check_id: str, status: str, evidence: list[str]) -> dict:
    return {"id": check_id, "kind": "automatic", "status": status, "evidence": evidence}
