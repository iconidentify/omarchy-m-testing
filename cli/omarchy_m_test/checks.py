"""The automatic checks of a run. Each check returns one schema-v1 check result.

run() detects the stack, wraps omarchy-mac's check scripts (scripts.py), adds
the checks they don't cover (hardware.py) and returns the results in ORDER
with the report's system block. On a reference distro the Omarchy-layer
results are skipped: only the hardware is compared with Omarchy.
"""

from __future__ import annotations

from . import hardware, scripts
from .catalogue import Catalogue
from .host import Host
from .machine import Machine
from .system import System

# Every automatic check id, in report order. Each is in the catalogue's checks.
ORDER = (
    "system.identity",
    "boot.kernel-package", "boot.chain", "boot.files", "boot.encryption",
    "packages.repositories", "packages.kernel-updates", "packages.hardware",
    "setup.first-boot-hardware", "setup.vendor-firmware",
    "system.failed-units", "system.snapshots",
    "gpu.driver", "gpu.vulkan", "gpu.opengl",
    "display.outputs", "display.controller", "display.backlight", "display.notch-strip",
    "audio.sound-cards", "audio.default-sink", "audio.speaker-dsp", "audio.speaker-protection",
    "audio.speaker-amps-unlocked", "audio.microphone-mapping",
    "network.wifi", "network.wifi-backend", "network.bluetooth",
    "input.ambient-light", "input.auto-keyboard-light",
    "power.battery",
    "cpu.frequency-scaling",
)


def system_identity(machine: Machine) -> dict:
    """Automatic check: the Mac's model, chip and kernel were identified."""
    evidence = [
        f"model: {machine.model}",
        f"compatible: {' '.join(machine.compatible)}",
        f"chip: {machine.chip} ({machine.soc})",
        f"kernel: {machine.kernel}",
    ]
    identified = machine.chip != "unknown" and machine.kernel != "unknown"
    return {
        "id": "system.identity",
        "kind": "automatic",
        "status": "pass" if identified else "fail",
        "evidence": evidence,
    }


def run(host: Host, machine: Machine, system: System, catalogue: Catalogue) -> tuple[list[dict], dict]:
    """Every automatic check's result, in ORDER, and the report's system block."""
    mac_check = scripts.mac_check(host)
    results = [system_identity(machine), *mac_check.results]
    results += scripts.audio_check(host, system)
    results += scripts.display_check(host, system)
    results += [
        hardware.encryption(system),
        hardware.hardware_packages(system),
        hardware.first_boot_setup(host),
        hardware.gpu_driver(host),
        hardware.gpu_vulkan(host, system),
        hardware.gpu_opengl(host),
        hardware.battery(host),
        hardware.cpu_scaling(host),
    ]
    by_id = {result["id"]: result for result in results}
    ordered = [by_id[check_id] for check_id in ORDER]
    if not system.is_omarchy:
        ordered = [_reference(result, system, catalogue) for result in ordered]
    return ordered, system.report(mac_check.boot_loader)


def _reference(result: dict, system: System, catalogue: Catalogue) -> dict:
    feature = catalogue.feature_for_check(result["id"])
    if feature is None or feature["layer"] != "omarchy":
        return result
    return {**result, "status": "skip", "evidence": [f"reference run on {system.distro}: Omarchy integration isn't checked"]}

