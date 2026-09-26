"""omarchy-mac's own check scripts, wrapped: their PASS/FAIL/SKIP lines become results.

The scripts are vendored unmodified (vendor/omarchy-mac/, see ORIGIN there)
and run through Host.run_bundled:

  mac-check                          every Omarchy stack and reference runs
  apple-audio-check.sh --no-sound    the converged image only (plays and records nothing)
  apple-display-check.sh --read-only the converged image only (changes no brightness)

mac-check runs its root-only checks (boot check, boot-file hashes, snapshots)
through sudo -n and prints SKIP "needs passwordless sudo" without it; those
become skipped results. Each result keeps the script's own lines as evidence.
Lines no result maps (mac-check's INFO lines, pending migrations, core dumps)
are software state rather than hardware results and stay out of the report;
the boot-loader line fills the report's system block.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .host import Host
from .system import System

# mac-check id -> check id.
MAC_CHECK = {
    "kernel": "boot.kernel-package",
    "boot-check": "boot.chain",
    "boot-file": "boot.files",
    "repos": "packages.repositories",
    "kernel-repo": "packages.kernel-updates",
    "vendor-firmware": "setup.vendor-firmware",
    "units": "system.failed-units",
    "snapshots": "system.snapshots",
    "displays": "display.outputs",
    "sound-cards": "audio.sound-cards",
    "default-sink": "audio.default-sink",
    "speakersafetyd": "audio.speaker-protection",
    "wifi": "network.wifi",
    "wifi-backend": "network.wifi-backend",
    "bluetooth": "network.bluetooth",
}
# apple-audio-check.sh description -> check id.
AUDIO_CHECK = {
    "speaker amps unlocked this boot": "audio.speaker-amps-unlocked",
    "speaker DSP sink present": "audio.speaker-dsp",
    "mic mapper running": "audio.microphone-mapping",
}
# apple-display-check.sh description -> check id.
DISPLAY_CHECK = {
    "the display controller card exists": "display.controller",
    "appledrm is showing the notch strip": "display.notch-strip",
    "the panel backlight is apple-panel-bl": "display.backlight",
    "ALS and keyboard LED are available": "input.ambient-light",
    "the ALS keyboard loop runs": "input.auto-keyboard-light",
}

_MAC_CHECK_LINE = re.compile(r"^(PASS|FAIL|WARN|SKIP|INFO)\s+(\S+)\s+(.*?)\s*$")
_AUDIO_LINE = re.compile(r"^(PASS|FAIL) (.+?)\s*$")
_DISPLAY_LINE = re.compile(r"^(ok|FAIL) - (.+?)\s*$")


@dataclass
class ScriptResults:
    results: list[dict] = field(default_factory=list)
    boot_loader: str = "unknown"


def _result(check_id: str, status: str, evidence: list[str]) -> dict:
    return {"id": check_id, "kind": "automatic", "status": status, "evidence": evidence}


def _from_lines(check_id: str, lines: list[tuple[str, str]], nothing: str) -> dict:
    """One result from a script's (status, line) pairs for it: any FAIL fails, all SKIP skips."""
    if not lines:
        return _result(check_id, "skip", [nothing])
    statuses = {status for status, _ in lines}
    if "FAIL" in statuses:
        status = "fail"
    elif statuses == {"SKIP"}:
        status = "skip"
    else:
        status = "pass"
    return _result(check_id, status, [line for _, line in lines])


def _why_not(name: str, run) -> str:
    detail = (run.stderr.strip().splitlines() or run.stdout.strip().splitlines() or [f"exit {run.returncode}"])[-1]
    return f"{name} didn't run: {detail}"


def mac_check(host: Host) -> ScriptResults:
    run = host.run_bundled("mac-check")
    found: dict[str, list[tuple[str, str]]] = {}
    boot_loader = "unknown"
    for raw in run.stdout.splitlines():
        match = _MAC_CHECK_LINE.match(raw)
        if not match:
            continue
        status, key, detail = match.groups()
        if key == "boot-loader":
            boot_loader = "limine" if detail.startswith("Limine") else "grub" if detail.startswith("GRUB") else "unknown"
        if key in MAC_CHECK:
            found.setdefault(key, []).append((status, raw.rstrip()))
    ran = bool(found) or run.returncode in (0, 1)
    results = [
        _from_lines(check_id, found.get(key, []), f"mac-check reported nothing for {key}" if ran else _why_not("mac-check", run))
        for key, check_id in MAC_CHECK.items()
    ]
    return ScriptResults(results, boot_loader)


def _manual_check(host: Host, system: System, name: str, args: list[str], pattern: re.Pattern, mapping: dict[str, str]) -> list[dict]:
    if system.stack != "converged":
        why = f"{name} checks the converged image's omarchy-mac integration; not run on {system.describe()}"
        return [_result(check_id, "skip", [why]) for check_id in mapping.values()]
    run = host.run_bundled(name, args)
    found: dict[str, list[tuple[str, str]]] = {}
    for raw in run.stdout.splitlines():
        match = pattern.match(raw)
        if match and match.group(2) in mapping:
            status = "PASS" if match.group(1) == "ok" else match.group(1)
            found.setdefault(match.group(2), []).append((status, raw.rstrip()))
    ran = bool(found) or run.returncode in (0, 1)
    return [
        _from_lines(check_id, found.get(description, []), f"{name} reported nothing for {description!r}" if ran else _why_not(name, run))
        for description, check_id in mapping.items()
    ]


def audio_check(host: Host, system: System) -> list[dict]:
    return _manual_check(host, system, "apple-audio-check", ["--no-sound"], _AUDIO_LINE, AUDIO_CHECK)


def display_check(host: Host, system: System) -> list[dict]:
    return _manual_check(host, system, "apple-display-check", ["--read-only"], _DISPLAY_LINE, DISPLAY_CHECK)
