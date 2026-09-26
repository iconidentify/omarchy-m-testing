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

from omarchy_m_test.host import CommandResult
from omarchy_m_test.recording import RecordedHost
from tests.desktop import command, recording, with_home

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CATALOGUE_PATH = "/test/catalogue.json"
NODE = "57"
WLAN = "wlan0"

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
    sudo_cached: bool = True
    session: dict[str, str] | None = field(default_factory=lambda: {"Remote": "no", "Seat": "seat0", "Active": "yes"})

    def copy(self) -> "MacState":
        return copy.deepcopy(self)


def live_recording(env: dict[str, str] | None = None, checkpoint: str | None = None, base: dict | None = None) -> dict[str, Any]:
    """The recorded M2 with $HOME, a login session, one Wi-Fi interface and the test catalogue."""
    rec = with_home(base or recording(), {"XDG_SESSION_ID": "2", **(env or {})}, checkpoint=checkpoint)
    rec["files"][CATALOGUE_PATH] = {"text": test_catalogue()}
    rec.setdefault("dirs", {}).update({
        "/sys/class/net": ["lo", WLAN],
        "/sys/class/net/lo": ["operstate"],
        f"/sys/class/net/{WLAN}": ["operstate", "wireless"],
    })
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
        if argv[:2] == ["pacman", "-Q"] and len(argv) > 2 and not recorded:  # the stack query stays as recorded
            names = argv[2:]
            found = "".join(f"{n} 1.0-1\n" for n in names if n in s.installed)
            missing = "".join(f"error: package '{n}' was not found\n" for n in names if n not in s.installed)
            return CommandResult(1 if missing else 0, found, missing)
        if argv[:5] == ["pacman", "-Sp", "--needed", "--print-format", "%n"]:
            plan: list[str] = []
            for name in argv[5:]:
                if name not in s.repository:
                    return CommandResult(1, "", f"error: target not found: {name}\n")
                plan += [p for p in s.repository[name] if p not in s.installed and p not in plan]
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
        if argv[:2] == ["loginctl", "show-session"]:
            if s.session is None:
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
