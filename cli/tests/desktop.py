"""Test helpers: a recorded Mac with (or without) an Omarchy desktop around it, and test sections.

The recordings in tests/recordings/ were made off a terminal, so they hold no
theme, logo or checkpoint. These helpers add what a run at a terminal reads,
as a recording would hold it.
"""

from __future__ import annotations

import copy
import json
import os
from typing import Any

from omarchy_m_test.host import CommandResult, Terminal
from omarchy_m_test.recording import EOF, RecordedHost
from omarchy_m_test.sections import APPLE
from omarchy_m_test.session import Context, Section

RECORDINGS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recordings")
HOME = "/home/tester"
CHECKPOINT = f"{HOME}/.local/state/omarchy-m-test/checkpoint.json"
THEME = f"{HOME}/.local/state/omarchy/current/theme"
OLD_THEME = f"{HOME}/.config/omarchy/current/theme"
TITLES = "\n".join(section.title for section in APPLE) + "\n"
LOGO_PATHS = ("/usr/share/omarchy/logo.txt", f"{HOME}/.local/share/omarchy/logo.txt")
TERMINAL = Terminal(120, 40)

# The recorded M2's human checks (notch bar, brightness steps, cursor, speaker
# tone, headphone jack, Bluetooth pairing, keyboard light, function keys,
# trackpad, USB-C devices, USB-C display), left unanswered as in its golden
# report: at a plain prompt (end of input) and at gum (Esc). A run that
# needs no answer after them ends its answers with ENDED instead.
UNANSWERED = [EOF] * 11
# How many human checks each corpus machine's run asks (the mx-mac M1's stand-ins skip three without asking;
# the converged M1 and M2 ran over SSH, where brightness can't be set, so that one isn't asked; the M1s have
# nothing plugged into their USB-C ports, so the two ports questions aren't asked).
HUMAN_QUESTIONS = {"m2-max-image2": 11, "m1-pro-mx-mac": 6, "m1-pro-converged": 8, "m2-max-converged": 10}
GUM_UNANSWERED = [CommandResult(1, "", "")] * 11
# How many of them come before the Wi-Fi first-join check asks to reload the driver (at a local seat only).
BEFORE_RELOAD = {"m2-max-image2": 6, "m1-pro-mx-mac": 4, "m1-pro-converged": 6, "m2-max-converged": 6}
# What only a run at a local seat asks besides: the Ports section's "plug in what you have" (after the reload).
AT_THE_SEAT_ONLY = 1


def at_the_seat(machine: str, reload: str | object = EOF) -> list:
    """A whole run's answers at the Mac, after the disclaimer: its questions unanswered, `reload` at the driver-reload question."""
    before = BEFORE_RELOAD[machine]
    return [*[EOF] * before, reload, *[EOF] * (HUMAN_QUESTIONS[machine] - before + AT_THE_SEAT_ONLY)]

LOGO = " ▄█████▄    ▄███████████▄\n███   ███  ███   ███   ███\n ▀█████▀    ▀█   ███   █▀"
SYSTEM_ART = "   ▄████████\n  ███    ███\n  ███    █▀ "
# A Catppuccin-like palette, so its colours can't be mistaken for Tokyo Night's.
COLORS_TOML = 'accent = "#89b4fa"\nforeground = "#cdd6f4"\ngreen = "#a6e3a1"\nred = "#f38ba8"\n'
RESOLVED = "accent\t#89b4fa\ndark_foreground\t#6c7086\nforeground\t#cdd6f4\ngreen\t#a6e3a1\nmode\tdark\nred\t#f38ba8\n"
GREEN_RGB = "38;2;166;227;161"        # #a6e3a1
ACCENT_RGB = "38;2;137;180;250"       # #89b4fa
GREY_RGB = "38;2;108;112;134"         # #6c7086
TOKYO_GREEN_RGB = "38;2;158;206;106"  # #9ece6a


def recording(name: str = "m2-max-image2") -> dict[str, Any]:
    with open(os.path.join(RECORDINGS, f"{name}.json"), encoding="utf-8") as f:
        return json.load(f)


def command(argv: list[str], stdout: str = "", returncode: int = 0, stderr: str = "") -> dict[str, Any]:
    return {"argv": argv, "returncode": returncode, "stdout": stdout, "stderr": stderr}


def with_home(rec: dict[str, Any], env: dict[str, str] | None = None, checkpoint: str | None = None) -> dict[str, Any]:
    """The recording with $HOME set, so the run checkpoints; optionally with a checkpoint left by an earlier run."""
    rec = copy.deepcopy(rec)
    rec.setdefault("env", {}).update({"HOME": HOME, **(env or {})})
    rec["files"][CHECKPOINT] = None if checkpoint is None else {"text": checkpoint}
    return rec


def omarchy_desktop(rec: dict[str, Any], env: dict[str, str] | None = None) -> dict[str, Any]:
    """An Omarchy install: logo, current theme, omarchy-theme-color, omarchy-ascii and gum."""
    rec = with_home(rec, env)
    rec["files"].update({
        LOGO_PATHS[0]: {"text": LOGO + "\n"},
        f"{THEME}/colors.toml": {"text": COLORS_TOML},
    })
    rec["commands"] += [
        command(["omarchy-theme-color", "--file", f"{THEME}/colors.toml", "--all"], RESOLVED),
        command(["omarchy-ascii", "--help"], "Usage: omarchy-ascii [text...]\n"),
        *(command(["omarchy-ascii", section.title], SYSTEM_ART + "\n") for section in APPLE),
        command(["gum", "--version"], "gum version 0.16.0\n"),
    ]
    return rec


def bare_desktop(rec: dict[str, Any], gum: bool = False, old_theme: str | None = None) -> dict[str, Any]:
    """No Omarchy files: another Asahi distro (or, with old_theme, an older Omarchy's theme dir)."""
    rec = with_home(rec)
    for path in LOGO_PATHS:
        rec["files"][path] = None
    for directory in (THEME, OLD_THEME):
        rec["files"][f"{directory}/colors.toml"] = None
        rec["files"][f"{directory}/alacritty.toml"] = None
    if old_theme is not None:
        rec["files"][f"{OLD_THEME}/colors.toml"] = {"text": old_theme}
        rec["commands"].append(command(["omarchy-theme-color", "--file", f"{OLD_THEME}/colors.toml", "--all"], "", 127, "not found\n"))
    rec["commands"] += [
        command(["omarchy-ascii", "--help"], "", 127, "omarchy-ascii: command not found\n"),
        command(["gum", "--version"], "gum version 0.16.0\n" if gum else "", 0 if gum else 127),
    ]
    return rec


def host(rec: dict[str, Any], answers=(), terminal: Terminal | None = None, **kwargs) -> RecordedHost:
    return RecordedHost(rec, answers=list(answers), terminal_size=terminal, **kwargs)


# -- sections that exercise the framework through the whole CLI -----------------

VOLUME_DOWN = ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "0.30"]
VOLUME_BACK = ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "0.45"]
MUTE = ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1"]
UNMUTE = ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"]
LISTEN = "Did you hear the tone? [y/n/s] "


def _tone(ctx: Context) -> list[dict]:
    ctx.change("the speaker volume", VOLUME_DOWN, VOLUME_BACK)
    ctx.change("the speaker mute", MUTE, UNMUTE)
    ctx.host.prompt(LISTEN)
    return []


def _kernel(ctx: Context) -> list[dict]:
    ctx.host.run(["uname", "-r"])
    ctx.host.run(FIRST_BOOT)
    return []


FIRST_BOOT = ["journalctl", "--unit=omarchy-provision-hardware.service", "--output=short-iso", "--no-pager"]
TONE = Section("tone", "Tone", "Plays a quiet tone.", (), _tone)
KERNEL = Section("kernel", "Kernel", "Reads the kernel release.", (), _kernel)
SECTIONS = (*APPLE, TONE)
FEED_SECTIONS = (*APPLE, KERNEL)


def with_section_commands(rec: dict[str, Any], restore_returncode: int = 0) -> dict[str, Any]:
    rec = copy.deepcopy(rec)
    rec["commands"] += [
        command(VOLUME_DOWN), command(VOLUME_BACK, returncode=restore_returncode, stderr="no default sink\n" if restore_returncode else ""),
        command(MUTE), command(UNMUTE),
    ]
    return rec
