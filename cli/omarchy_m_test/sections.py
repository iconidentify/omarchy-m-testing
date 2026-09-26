"""The sections of a run on an Apple Silicon Mac, in order.

Each section names the check ids it reports, in report order, so a skipped
section still reports every one of its checks (as skipped). Together they
are checks.ORDER. Titles are drawn in the logo's font, which has letters and
spaces only; keep them short.
"""

from __future__ import annotations

from typing import Callable

from . import checks
from .session import Context, Section


def _section(id: str, title: str, description: str, check_ids: tuple[str, ...], run: Callable[[Context], list[dict]],
             human_checks: tuple[str, ...] = ()) -> Section:
    return Section(id, title, description, check_ids, lambda ctx: checks.only(check_ids, run(ctx), ctx), human_checks)


APPLE: tuple[Section, ...] = (
    _section("boot", "Boot", "Model and kernel, boot chain and files, encryption, packages, first-boot setup, services and snapshots.", (
        "system.identity",
        "boot.kernel-package", "boot.chain", "boot.files", "boot.encryption",
        "packages.repositories", "packages.kernel-updates", "packages.hardware",
        "setup.first-boot-hardware", "setup.vendor-firmware",
        "system.failed-units", "system.snapshots",
    ), checks.boot),
    _section("hardware", "Hardware", "Every hardware node and whether a driver claimed it, firmware and probe errors, and the kernel's build options against Asahi's.", (
        "hardware.drivers", "hardware.firmware", "hardware.probe-errors", "hardware.kernel-config",
    ), checks.hardware_inventory),
    _section("graphics", "Graphics", "The GPU driver, Vulkan and OpenGL.", ("gpu.driver", "gpu.vulkan", "gpu.opengl"), checks.graphics),
    _section("display", "Display", "Outputs, the display controller, the backlight and the notch strip; then you look: the bar and the notch, brightness steps, the cursor.", (
        "display.outputs", "display.controller", "display.backlight", "display.notch-strip",
        "display.notch-bar", "display.brightness-steps", "display.cursor",
    ), checks.display, ("display.notch-bar", "display.brightness-steps", "display.cursor")),
    _section("audio", "Audio", "Sound cards, the default sink, speaker DSP and protection, the microphone mapping; then the microphone, a short tone at 30% volume (only once speaker protection is confirmed) and the headphone jack.", (
        "audio.sound-cards", "audio.default-sink", "audio.speaker-dsp", "audio.speaker-protection",
        "audio.speaker-amps-unlocked", "audio.microphone-mapping",
        "audio.microphone-signal", "audio.speaker-tone", "audio.headphone-detection",
    ), checks.audio, ("audio.speaker-tone", "audio.headphone-detection")),
    _section("network", "Network", "Wi-Fi, its backend and Bluetooth.", ("network.wifi", "network.wifi-backend", "network.bluetooth"), checks.network),
    _section("input", "Input", "The ambient light sensor and the automatic keyboard light; then you cover the sensor and watch the keyboard light.", (
        "input.ambient-light", "input.auto-keyboard-light", "input.keyboard-light-follows-room",
    ), checks.input_devices, ("input.keyboard-light-follows-room",)),
    _section("power", "Power", "The battery.", ("power.battery",), checks.power),
    _section("cpu", "CPU", "CPU frequency scaling.", ("cpu.frequency-scaling",), checks.cpu),
)
