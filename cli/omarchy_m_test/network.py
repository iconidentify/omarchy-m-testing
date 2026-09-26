"""The Network section's live checks: Bluetooth pairing, and the first Wi-Fi join after the driver starts.

Bluetooth pairing (human): with mac-check's powered controller, the human
pairs a device (headphones, a mouse, a keyboard) from Omarchy's Bluetooth
menu and says whether it paired and works. The number of paired devices
before and after is kept as evidence; no device name or address is ever
read into the report (the count is taken on the Mac). The device stays
paired: it's the human's own change.

First join (automatic, disruptive): omarchy-mac issue 73. On the M2 Max's
BCM4388 the first join after the firmware loads could report "connected" in
0.23 s and then get no DHCP lease (it had landed on the network's 6 GHz
radio, where the uplink was dropped); the second join worked. The check
reproduces a first join the way a boot does, by reloading the driver
(changes.reload_wifi_driver), and measures it:

  - only with a rejoin path (changes.wifi_link): never over SSH (so never
    over an SSH session on this Wi-Fi) and only at a local seat, Wi-Fi
    associated on brcmfmac with an address, on a NetworkManager connection
    that connects automatically, which NetworkManager then rejoins by itself;
  - only on a 5 GHz (or 6 GHz) network: on 2.4 GHz it's skipped;
  - only after the human agrees (Wi-Fi drops for up to a minute) and sudo
    works (modprobe);
  - a few lines of shell on the Mac (WATCH_SCRIPT) then poll every 0.2 s
    for WATCH_SECONDS from the moment the driver is loaded again: each time
    the interface associates or drops (operstate up/down), and the first
    IPv4 address (not link-local). They print only times, the channel's
    frequency and whether the connection is the original one: never an
    address or a network name.

It passes when the first association after the reload carries an address
(traffic arrived) within WATCH_SECONDS, on the original connection. The
evidence records when it associated, when the address arrived, the band
and how many joins it took. No association, or no address before that first
association dropped or the time ran out, fails. NetworkManager joining a
different saved network is skipped: it says nothing about this one's first
join. The restorers put the driver and the original connection back when
the section ends, also after Ctrl-C.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import changes, human
from .session import Context
from .ui import Ui

FIRST_JOIN = "network.wifi-first-join"
PAIRING = "network.bluetooth-pairing"
WATCH_SECONDS = 50  # NetworkManager's DHCP timeout is 45 s; and under the host's 60 s per command

# Run as `sh -c SCRIPT sh INTERFACE UUID SECONDS`. Times are hundredths of a second since it started.
WATCH_SCRIPT = r"""iface=$1 uuid=$2 limit=$3
start=$(date +%s%N)
state=down
while :; do
  t=$(( ($(date +%s%N) - start) / 10000000 ))
  if [ "$t" -ge $((limit * 100)) ]; then echo "timeout $t"; break; fi
  op=$(cat "/sys/class/net/$iface/operstate" 2>/dev/null)
  if [ "$op" = up ]; then
    if [ "$state" = down ]; then echo "up $t"; state=up; fi
    if ip -4 -o address show dev "$iface" 2>/dev/null | grep -v " inet 169\.254\." | grep -q " inet "; then echo "address $t"; break; fi
  elif [ "$state" = up ]; then echo "down $t"; state=down; fi
  sleep 0.2
done
freq=$(iw dev "$iface" link 2>/dev/null | awk '/freq:/ { print int($2); exit }')
if [ -n "$freq" ]; then echo "freq $freq"; fi
if [ "$(nmcli -g GENERAL.CON-UUID device show "$iface" 2>/dev/null)" = "$uuid" ]; then echo "connection same"; else echo "connection other"; fi"""

# Run as `sh -c SCRIPT`: how many devices BlueZ has paired; never their names or addresses.
PAIRED_SCRIPT = 'timeout 5 bluetoothctl devices Paired 2>/dev/null | grep -c "^Device "'
PAIRED = ["sh", "-c", PAIRED_SCRIPT]

RELOAD_WARNING = (
    "The first-join check reloads the Wi-Fi driver, as a boot does, and times how the Mac joins this network again: "
    f"Wi-Fi drops now for up to {WATCH_SECONDS} s. It comes back by itself, and the connection is put back if it doesn't."
)
RELOAD_QUESTION = "Reload the Wi-Fi driver now?"
PAIRING_QUESTION = (
    "Put a Bluetooth device (headphones, a mouse or a keyboard) in pairing mode and pair it: "
    "open Bluetooth (Super+Ctrl+B in Omarchy, or bluetui) and pick it (s if you have none to hand). Did it pair and work?"
)


def watch_argv(link: changes.WifiLink, seconds: int = WATCH_SECONDS) -> list[str]:
    return ["sh", "-c", WATCH_SCRIPT, "sh", link.interface, link.connection, str(seconds)]


def band(frequency: int | None) -> str:
    if frequency is None:
        return "not associated (iw couldn't say)"
    if frequency < 3000:
        return f"2.4 GHz ({frequency} MHz)"
    if frequency < 5925:
        return f"5 GHz ({frequency} MHz)"
    return f"6 GHz ({frequency} MHz)"


@dataclass
class Watched:
    """What WATCH_SCRIPT saw, in seconds since the driver was loaded again."""

    ups: list[float] = field(default_factory=list)
    downs: list[float] = field(default_factory=list)
    address: float | None = None
    timeout: float | None = None
    frequency: int | None = None
    same_connection: bool = False
    understood: bool = False


def parse_watch(stdout: str) -> Watched:
    watched = Watched()
    for line in stdout.splitlines():
        word, _, value = line.strip().partition(" ")
        if not value.isdigit():
            continue
        if word in ("up", "down", "address", "timeout"):
            watched.understood = True
            seconds = int(value) / 100
            if word == "up":
                watched.ups.append(seconds)
            elif word == "down":
                watched.downs.append(seconds)
            elif word == "address":
                watched.address = seconds
            else:
                watched.timeout = seconds
        elif word == "freq":
            watched.frequency = int(value)
    watched.same_connection = any(line.strip() == "connection same" for line in stdout.splitlines())
    return watched


# -- the first Wi-Fi join ----------------------------------------------------------

def first_join(ctx: Context) -> dict:
    why, link = changes.wifi_link(ctx)
    if why:
        return _automatic(FIRST_JOIN, "skip", [f"skipped: {why}"])
    assert link is not None
    evidence = [
        f"before: associated on {band(link.frequency)} with an address, on a NetworkManager connection that connects automatically",
    ]
    if link.frequency is None:
        return _automatic(FIRST_JOIN, "skip", [*evidence, "skipped: iw couldn't say which band Wi-Fi is on"])
    if link.frequency < 5000:
        return _automatic(FIRST_JOIN, "skip", [*evidence, "skipped: the check needs a 5 GHz network; join one and run it again"])

    ui = ctx.ui or Ui(ctx.host)
    ui.text(RELOAD_WARNING)
    if not ui.confirm(RELOAD_QUESTION, default=False):
        return _automatic(FIRST_JOIN, "skip", [*evidence, "skipped: you chose not to reload the Wi-Fi driver"])

    why, broke = changes.reload_wifi_driver(ctx, link)
    if why:
        return _automatic(FIRST_JOIN, "fail" if broke else "skip", [*evidence, why if broke else f"skipped: {why}"])
    evidence.append(f"reloaded the Wi-Fi driver ({changes.WIFI_DRIVER}); watched the rejoin for {WATCH_SECONDS} s")
    watched = parse_watch(ctx.host.run(watch_argv(link)).stdout)
    return _automatic(FIRST_JOIN, *_judge(watched, evidence))


def _judge(watched: Watched, evidence: list[str]) -> tuple[str, list[str]]:
    if not watched.understood:
        return "skip", [*evidence, "skipped: the rejoin couldn't be watched"]
    if not watched.ups:
        return "fail", [*evidence, f"no join: Wi-Fi didn't associate within {WATCH_SECONDS} s of the driver loading"]
    first = watched.ups[0]
    evidence.append(f"first join: associated {first:.2f} s after the driver loaded")
    dropped = next((t for t in watched.downs if t > first), None)
    if watched.address is not None and not watched.same_connection:
        return "skip", [*evidence, "skipped: NetworkManager joined another saved network, so this one's first join wasn't seen"]
    if watched.address is not None and dropped is None:
        evidence += [
            f"first join: an address (traffic) arrived {watched.address:.2f} s after the driver loaded, "
            f"{watched.address - first:.2f} s after associating",
            f"band: {band(watched.frequency)}",
            "joins: 1",
        ]
        return "pass", evidence
    if dropped is not None:
        evidence.append(f"first join: no address (no traffic) before it dropped {dropped:.2f} s after the driver loaded")
        if watched.address is not None:
            evidence.append(f"join {len(watched.ups)}: an address arrived {watched.address:.2f} s after the driver loaded")
    else:
        end = watched.timeout if watched.timeout is not None else float(WATCH_SECONDS)
        evidence.append(f"first join: associated but no address (no traffic) in the {end - first:.2f} s it stayed associated")
    evidence += [f"band at the end: {band(watched.frequency)}", f"joins: {len(watched.ups)}"]
    return "fail", evidence


# -- Bluetooth pairing ------------------------------------------------------------------

def _paired(ctx: Context) -> int | None:
    count = ctx.host.run(PAIRED).stdout.strip()
    return int(count) if count.isdigit() else None


def pairing(ctx: Context, controller: dict | None) -> dict:
    if controller is None or controller.get("status") != "pass":
        return human.skip(PAIRING, "no powered Bluetooth controller (see network.bluetooth)")
    before = _paired(ctx)
    result = human.check(ctx, PAIRING, PAIRING_QUESTION)
    after = _paired(ctx)
    counted = "couldn't be counted" if before is None or after is None else f"{before} before, {after} after"
    result["evidence"].insert(0, "Bluetooth controller powered (mac-check)")
    result["evidence"].append(f"paired devices: {counted}")
    if result["status"] == "pass":
        _say(ctx, "The device stays paired; remove it from Bluetooth if you don't want it.")
    return result


def run(ctx: Context, automatic: list[dict]) -> list[dict]:
    """The live checks after mac-check's: pairing while Wi-Fi is up, then the first join (last: it drops Wi-Fi)."""
    controller = next((result for result in automatic if result["id"] == "network.bluetooth"), None)
    return [pairing(ctx, controller), first_join(ctx)]


def _say(ctx: Context, text: str) -> None:
    if ctx.ui:
        ctx.ui.text(text)
    else:
        ctx.host.show(text)


def _automatic(check_id: str, status: str, evidence: list[str]) -> dict:
    return {"id": check_id, "kind": "automatic", "status": status, "evidence": evidence}
