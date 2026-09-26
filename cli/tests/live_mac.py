"""Test helper: a recorded Mac whose volume, Wi-Fi, packages and login session change as the CLI changes them.

A plain RecordedHost answers every command the same way each time. The
interactive framework reads state, changes it and reads it back, so LiveMac
answers these commands from a small model of the Mac, and everything else
from the recording:

  wpctl inspect/get-volume/set-volume/set-mute   the default sink (node 57)
  rfkill                                         the Wi-Fi radio
  pacman -Q / -Sp, sudo -n pacman -S / -R        installed packages and the repositories
  sudo -n true                                   whether sudo has cached credentials
  loginctl show-session                          the run's login session
  modprobe brcmfmac, nmcli, the join watch       the Wi-Fi driver, the connection and its first join
  bluetoothctl's paired-device count             when the test gives one

Tests assert on the model's state at the end (was everything put back?) and
on the commands the Mac was sent. Nothing here ever asks for a password:
sudo -v is an interactive command, answered from the scripted answers.
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from typing import Any

from omarchy_m_test import changes, network
from omarchy_m_test.host import CommandResult
from omarchy_m_test.recording import RecordedHost
from tests.desktop import command, recording, with_home

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CATALOGUE_PATH = "/test/catalogue.json"
NODE = "57"
WLAN = "wlan0"
# The Wi-Fi connection's NetworkManager UUID (made up; the real one is never recorded in a report).
CONNECTION = "3f0c2a8e-5b1d-4c7e-9a64-2d8b1e0f7c35"
UEVENT = f"/sys/class/net/{WLAN}/device/uevent"
UNLOAD = changes.unload_wifi_driver_argv(["brcmfmac_wcc", "brcmfmac"])
LOAD = changes.LOAD_WIFI_DRIVER
RECONNECT = changes.reconnect_argv(CONNECTION)
WATCH = network.watch_argv(changes.WifiLink(WLAN, CONNECTION, 5240))

# What the join watch prints after a driver reload (hundredths of a second since the driver loaded).
# A good first join, as omarchy-mac's check saw it with the fix on the M2 Max
# (operations/asahi-brcmfmac-6ghz-73/logs/after-auto.txt: 5240 MHz, an address 2.6 s after the reload;
# the association time isn't in that log and is reconstructed).
GOOD_JOIN = "up 212\naddress 260\nfreq 5240\nconnection same\n"
# The recorded first-join failure (boot-1-failure.log, before-6ghz-auto.txt, manual-check-repro.txt): the
# first join after the firmware loads lands on the network's 6 GHz radio (6135 MHz), reports connected and gets
# no DHCP lease; the reload's association time is reconstructed.
FAILED_JOIN = "up 187\ntimeout 4500\nfreq 6135\nconnection same\n"

# Check ids the test sections report, added to a copy of the bundled catalogue.
TEST_CHECKS = {
    "test.tone-heard": "speakers",
    "test.wifi-rejoin": "wifi",
    "test.benchmark": "gpu",
    "test.forbidden": "boot-chain",
}


def test_catalogue() -> str:
    with open(os.path.join(REPO, "catalogue", "catalogue.json"), encoding="utf-8") as f:
        data = json.load(f)
    data["checks"].update(TEST_CHECKS)
    return json.dumps(data)


@dataclass
class MacState:
    volume: str = "0.45"
    muted: bool = False
    has_sink: bool = True
    wifi_blocked: bool = False
    wifi_up: bool = True
    installed: set[str] = field(default_factory=lambda: {"mesa", "pipewire"})
    # What installing a package brings in, dependencies first (as pacman -Sp prints it).
    repository: dict[str, list[str]] = field(default_factory=lambda: {
        "glmark2": ["libpng12", "glmark2"],
        "vkmark": ["vkmark"],
        "mesa": ["mesa"],
        "bootpull": ["linux-firmware", "bootpull"],
    })
    install_fails_after: int | None = None  # installs only the first N packages, then fails
    outdated: set[str] = field(default_factory=set)  # installed, but a dependency needs a newer one (pacman -Sp lists them)
    volume_fails: bool = False
    sudo_cached: bool = True
    session: dict[str, str] | None = field(default_factory=lambda: {"Remote": "no", "Seat": "seat0", "Active": "yes"})
    session_ids: tuple[str, ...] = ("2", "auto")  # the ids logind answers for
    wifi_driver: bool = True  # brcmfmac loaded
    connection_active: bool = True  # NetworkManager has the Wi-Fi connection activated
    frequency: str = "5240"  # MHz, the band Wi-Fi is on before the check
    join: str = GOOD_JOIN  # what the join watch prints after a reload
    reconnects: bool = True  # nmcli connection up works
    driver_loads: bool = True  # modprobe brcmfmac works
    paired: list[int] | None = None  # the paired-device counts BlueZ gives, in turn (the last one stays); None: as recorded

    def copy(self) -> "MacState":
        return copy.deepcopy(self)


def live_recording(env: dict[str, str] | None = None, checkpoint: str | None = None, base: dict | None = None) -> dict[str, Any]:
    """The recorded M2 with $HOME, a login session, one Wi-Fi interface and the test catalogue."""
    rec = with_home(base or recording(), {"XDG_SESSION_ID": "2", **(env or {})}, checkpoint=checkpoint)
    rec["files"][CATALOGUE_PATH] = {"text": test_catalogue()}
    rec.setdefault("dirs", {}).update({
        "/sys/class/net": ["lo", WLAN],
        "/sys/class/net/lo": ["operstate"],
        f"/sys/class/net/{WLAN}": ["device", "operstate", "wireless"],
    })
    rec["files"].update({
        UEVENT: {"text": "DRIVER=brcmfmac\nPCI_CLASS=28000\nPCI_ID=14E4:4433\n"},
        "/sys/module/brcmfmac/initstate": {"text": "live\n"},
        "/sys/module/brcmfmac_wcc/initstate": {"text": "live\n"},
    })
    rec["commands"] += [
        command(["nmcli", "-g", "connection.autoconnect", "connection", "show", CONNECTION], "yes\n"),
        command(changes.addresses_argv(WLAN), "1\n"),
        command(["sleep", "1"]),
    ]
    return rec


class LiveMac(RecordedHost):
    def __init__(self, rec: dict[str, Any], state: MacState | None = None, **kwargs: Any):
        super().__init__(rec, **kwargs)
        self.state = state or MacState()

    def read_file(self, path: str) -> bytes:
        if path == f"/sys/class/net/{WLAN}/operstate":
            return b"up\n" if self.state.wifi_up and not self.state.wifi_blocked else b"down\n"
        if path == "/sys/class/net/lo/operstate":
            return b"unknown\n"
        return super().read_file(path)

    def run(self, argv):
        argv = list(argv)
        answer = self._answer(argv)
        if answer is None:
            return super().run(argv)
        self.commands_run.append(argv)
        return answer

    def _answer(self, argv: list[str]) -> CommandResult | None:
        s = self.state
        ok = CommandResult(0, "", "")
        if argv == ["wpctl", "inspect", "@DEFAULT_AUDIO_SINK@"]:
            return CommandResult(0, f"id {NODE}, type PipeWire:Interface:Node\n", "") if s.has_sink else CommandResult(1, "", "Object not found\n")
        if argv == ["wpctl", "get-volume", NODE]:
            return CommandResult(0, f"Volume: {s.volume}{' [MUTED]' if s.muted else ''}\n", "")
        if argv[:3] == ["wpctl", "set-volume", NODE]:
            if s.volume_fails:
                return CommandResult(1, "", "Node not found\n")
            s.volume = argv[3]
            return ok
        if argv[:3] == ["wpctl", "set-mute", NODE]:
            s.muted = argv[3] == "1"
            return ok
        if argv[:1] == ["rfkill"]:
            if argv[1:2] == ["block"]:
                s.wifi_blocked = True
                return ok
            if argv[1:2] == ["unblock"]:
                s.wifi_blocked = False
                return ok
            soft = "blocked" if s.wifi_blocked else "unblocked"
            return CommandResult(0, f"bluetooth unblocked unblocked\nwlan {soft} unblocked\n", "")
        if argv == ["sudo", "-n", "true"]:
            return ok if s.sudo_cached else CommandResult(1, "", "sudo: a password is required\n")
        recorded = any(entry["argv"] == argv for entry in self.recording.get("commands", []))
        if argv[1:2] in (["-Q"], ["-Qq"]) and argv[0] == "pacman" and len(argv) > 2 and not recorded:  # the stack query stays as recorded
            names = argv[2:]
            found = "".join(f"{n}\n" if argv[1] == "-Qq" else f"{n} 1.0-1\n" for n in names if n in s.installed)
            missing = "".join(f"error: package '{n}' was not found\n" for n in names if n not in s.installed)
            return CommandResult(1 if missing else 0, found, missing)
        if argv[:5] == ["pacman", "-Sp", "--needed", "--print-format", "%n"]:
            plan: list[str] = []
            for name in argv[5:]:
                if name not in s.repository:
                    return CommandResult(1, "", f"error: target not found: {name}\n")
                plan += [p for p in s.repository[name] if (p not in s.installed or p in s.outdated) and p not in plan]
            return CommandResult(0, "".join(p + "\n" for p in plan), "")
        if argv[:4] == ["sudo", "-n", "pacman", "-S"]:
            if not s.sudo_cached:
                return CommandResult(1, "", "sudo: a password is required\n")
            names = [a for a in argv[4:] if not a.startswith("-")]
            plan = [p for n in names for p in s.repository[n] if p not in s.installed]
            if s.install_fails_after is not None:
                s.installed.update(plan[: s.install_fails_after])
                return CommandResult(1, "", "error: failed to commit transaction (download failed)\n")
            s.installed.update(plan)
            return ok
        if argv[:4] == ["sudo", "-n", "pacman", "-R"]:
            names = [a for a in argv[4:] if not a.startswith("-")]
            if not s.sudo_cached:
                return CommandResult(1, "", "sudo: a password is required\n")
            if any(n not in s.installed for n in names):
                return CommandResult(1, "", "error: target not found\n")
            s.installed.difference_update(names)
            return ok
        if argv == ["nmcli", "-g", "GENERAL.STATE,GENERAL.CON-UUID", "device", "show", WLAN]:
            if not s.wifi_driver:
                return CommandResult(10, "", f"Error: Device '{WLAN}' not found.\n")
            return CommandResult(0, f"100 (connected)\n{CONNECTION}\n" if s.connection_active else "30 (disconnected)\n\n", "")
        if argv == changes.frequency_argv(WLAN):
            return CommandResult(0, f"{s.frequency}\n" if s.connection_active else "", "")
        if argv == UNLOAD:
            if not s.sudo_cached:
                return CommandResult(1, "", "sudo: a password is required\n")
            s.wifi_driver = s.connection_active = s.wifi_up = False
            return ok
        if argv == LOAD:
            if not s.driver_loads:
                return CommandResult(1, "", "modprobe: ERROR: could not insert 'brcmfmac': No such device\n")
            s.wifi_driver = True
            return ok
        if argv == WATCH:
            if s.wifi_driver and "address" in s.join:
                s.connection_active = s.wifi_up = True
            return CommandResult(0, s.join, "")
        if argv == RECONNECT:
            if not s.connection_active and s.wifi_driver and s.reconnects:
                s.connection_active = s.wifi_up = True
            return ok if s.connection_active else CommandResult(4, "", "Error: Connection activation failed.\n")
        if argv == network.PAIRED and s.paired is not None:
            count = s.paired.pop(0) if len(s.paired) > 1 else s.paired[0]
            return CommandResult(0 if count else 1, f"{count}\n", "")
        if argv[:2] == ["loginctl", "show-session"]:
            if s.session is None or argv[2] not in s.session_ids:
                return CommandResult(1, "", "Failed to get session: No session\n")
            return CommandResult(0, "".join(f"{k}={v}\n" for k, v in s.session.items()), "")
        return None

    def run_tty(self, argv, env=None):
        result = super().run_tty(argv, env)
        if list(argv) == ["sudo", "-v"] and result.returncode == 0:
            self.state.sudo_cached = True
        return result


def ascii_titles(rec: dict[str, Any], titles: list[str], art: str) -> dict[str, Any]:
    """omarchy-ascii answers for the test sections' titles (a run at an Omarchy terminal draws them)."""
    rec["commands"] += [command(["omarchy-ascii", title], art + "\n") for title in titles]
    return rec
