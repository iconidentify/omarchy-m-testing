"""External outputs at their own EDID preferred resolution, without changing a mode.

Refresh is evidence only: a lower refresh can be intentional or a link limit.
Hyprland reports unscaled, untransformed mode pixels; rotate both current and
preferred dimensions into the same orientation, never multiply by scale.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass

from . import ports
from .host import Host, TimedOut
from .session import Context

CHECK_ID = "display.external-native-mode"
MONITORS = ["hyprctl", "-j", "monitors", "all"]
SETTLE_SECONDS = 2
KERNEL_LOG = ["timeout", "3", "journalctl", "--dmesg", "--boot=0", "--output=cat", "--no-pager"]
DRM = "/sys/class/drm"
CONNECTOR = re.compile(r"(card\d+)-((?:USB|DP|HDMI-A|HDMI-B|DVI-D|DVI-I|DVI-A|VGA)-\d+)")


@dataclass(frozen=True)
class Mode:
    width: int
    height: int
    refresh: float

    def oriented(self, transform: int) -> tuple[int, int]:
        return (self.height, self.width) if transform % 2 else (self.width, self.height)

    def describe(self) -> str:
        return f"{self.width}x{self.height}@{self.refresh:.2f}Hz"


def preferred_mode(edid: bytes) -> Mode | None:
    """Only the base block's first detailed timing, never EDID identity fields."""
    if (len(edid) < 128 or edid[:8] != b"\x00\xff\xff\xff\xff\xff\xff\x00"
            or sum(edid[:128]) % 256 or edid[18] != 1 or not edid[24] & 2):
        return None
    timing = edid[54:72]
    clock = int.from_bytes(timing[:2], "little") * 10_000
    width = timing[2] | (timing[4] & 0xf0) << 4
    height = timing[5] | (timing[7] & 0xf0) << 4
    hblank = timing[3] | (timing[4] & 0x0f) << 8
    vblank = timing[6] | (timing[7] & 0x0f) << 8
    if not all((clock, width, height, hblank, vblank)) or timing[17] & 0x80:
        return None
    return Mode(width, height, clock / ((width + hblank) * (height + vblank)))


def anonymous_edid(edid: bytes) -> bytes | None:
    """A replayable timing block with no manufacturer, product, serial or strings."""
    if preferred_mode(edid) is None:
        return None
    block = bytearray(128)
    block[:8] = edid[:8]
    block[18:20] = edid[18:20]
    block[24] = 2
    block[54:62] = edid[54:62]
    block[127] = -sum(block) % 256
    return bytes(block)


def _result(status: str, evidence: list[str]) -> dict:
    return {"id": CHECK_ID, "kind": "automatic", "status": status, "evidence": evidence}


def _connected(host: Host) -> list[tuple[str, str]] | None:
    listed = host.run(ports.DISPLAYS_LIST)
    if listed.returncode != 0:
        return None
    found = []
    for line in listed.stdout.splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[0] == "connector" and fields[2] == "connected":
            match = CONNECTOR.fullmatch(fields[1])
            if match:
                found.append((match[1], match[2]))
    return found


def _monitors(host: Host) -> list[dict] | None:
    try:
        result = host.run(MONITORS)
    except TimedOut:
        return None
    if result.returncode != 0:
        return None
    try:
        monitors = json.loads(result.stdout)
    except ValueError:
        return None
    if not isinstance(monitors, list) or not all(isinstance(m, dict) and isinstance(m.get("name"), str) for m in monitors):
        return None
    return monitors


def _current(monitor: dict) -> tuple[Mode, int] | None:
    try:
        width, height = int(monitor["width"]), int(monitor["height"])
        refresh, transform = float(monitor.get("refreshRate", 0)), int(monitor.get("transform", 0))
    except (KeyError, ValueError, TypeError, OverflowError):
        return None
    if width <= 0 or height <= 0 or not math.isfinite(refresh) or not 0 <= transform <= 7:
        return None
    return Mode(width, height, refresh), transform


def _evaluate(host: Host, connectors: list[tuple[str, str]], monitors: list[dict]) -> dict:
    evidence = ["resolution compared in physical pixels; refresh reported only"]
    by_name = {m["name"]: m for m in monitors}
    intents = host.monitor_intent([{"name": name, "description": by_name.get(name, {}).get("description", "")}
                                   for _, name in connectors])
    mirrored = set()
    for monitor in monitors:
        target = str(monitor.get("mirrorOf", "none"))
        if target not in ("none", "None", "", "-1"):
            mirrored.add(monitor["name"])
            mirrored.update(m["name"] for m in monitors if str(m.get("id")) == target or m["name"] == target)
    statuses = []
    for card, name in connectors:
        monitor = by_name.get(name, {})
        intent = intents[name]
        reason = None
        if intent["disabled"] or monitor.get("disabled") or monitor.get("dpmsStatus") is False:
            reason = "output disabled on purpose"
        elif intent["mirrored"] or name in mirrored:
            reason = "output participates in mirroring"
        elif intent["unavailable"]:
            reason = "Hyprland monitor rules unavailable or computed; mode intent unknown"
        elif not intent["preferred"]:
            reason = "explicit monitor mode configured"
        elif not monitor:
            reason = "connected output unavailable in Hyprland"
        current = _current(monitor)
        if reason is None and current is None:
            reason = "current mode unavailable in Hyprland"
        preferred = None
        if reason is None:
            try:
                preferred = preferred_mode(host.read_file(f"{DRM}/{card}-{name}/edid"))
            except OSError:
                pass
            if preferred is None:
                reason = "EDID missing, unreadable or has no parseable preferred detailed timing"
        if reason:
            statuses.append("skip")
            evidence.append(f"{name}: skipped: {reason}")
            continue
        mode, transform = current
        now, wanted = mode.oriented(transform), preferred.oriented(transform)
        detail = f"{name}: current {mode.describe()}, EDID preferred {preferred.describe()}, transform {transform}"
        if now == wanted:
            statuses.append("pass")
            evidence.append(detail)
        elif any(actual < native for actual, native in zip(now, wanted)):
            statuses.append("fail")
            evidence.append(f"{detail}; below preferred resolution")
        else:
            statuses.append("skip")
            evidence.append(f"{detail}; skipped: current resolution exceeds the EDID preference")
    status = "fail" if "fail" in statuses else "skip" if "skip" in statuses else "pass"
    return _result(status, evidence)


def check(ctx: Context) -> dict:
    connectors = _connected(ctx.host)
    if connectors is None:
        return _result("skip", ["skipped: DRM connector state unavailable"])
    if not connectors:
        return _result("skip", ["skipped: no external display connected"])
    monitors = _monitors(ctx.host)
    if monitors is None:
        return _result("skip", ["skipped: Hyprland session or monitor list unavailable"])
    result = _evaluate(ctx.host, connectors, monitors)
    if result["status"] == "fail":
        ctx.host.sleep(SETTLE_SECONDS)
        connectors, monitors = _connected(ctx.host), _monitors(ctx.host)
        if connectors is None or monitors is None:
            result = _result("skip", ["skipped: display state unavailable after settling"])
        elif not connectors:
            result = _result("skip", ["skipped: no external display connected after settling"])
        else:
            result = _evaluate(ctx.host, connectors, monitors)
        result["evidence"].append(f"re-read after {SETTLE_SECONDS}s settling")
    result["evidence"].extend(diagnostics(ctx.host, connectors or []))
    return result


def _text(host: Host, path: str) -> str:
    try:
        return host.read_file(path).decode("utf-8", "replace")
    except OSError:
        return ""


def _debug_crtcs(state: str) -> dict[str, str]:
    crtcs = {name.strip(): ident for ident, name in re.findall(r"^crtc\[(\d+)\]:([^\n]+)", state, re.M)}
    found = {}
    for block in re.split(r"(?=^connector\[)", state, flags=re.M)[1:]:
        name = re.match(r"connector\[\d+\]:([^\n]+)", block)
        crtc = re.search(r"^\s+crtc=([^\n]+)", block, re.M)
        if name and crtc:
            value = crtc[1].strip()
            found[name[1].strip()] = crtcs.get(value, value)
    return found


def drm_info_argv(card: str) -> list[str]:
    return ["timeout", "3", "drm_info", "-j", f"/dev/dri/{card}"]


def diagnostics(host: Host, connectors: list[tuple[str, str]]) -> list[str]:
    """Optional reads never decide a result, including when a tool times out."""
    evidence = []
    for card in sorted({card for card, _ in connectors}):
        crtcs = _debug_crtcs(_text(host, f"/sys/kernel/debug/dri/{card[4:]}/state"))
        missing = [name for c, name in connectors if c == card and name not in crtcs]
        if missing:
            try:
                info = host.run(drm_info_argv(card))
                device = json.loads(info.stdout).get(f"/dev/dri/{card}", {}) if info.returncode == 0 else {}
                for name in missing:
                    ident = _text(host, f"{DRM}/{card}-{name}/connector_id").strip()
                    connector = next((c for c in device.get("connectors", []) if str(c.get("id")) == ident), {})
                    value = connector.get("properties", {}).get("CRTC_ID", {}).get("value")
                    if isinstance(value, int):
                        crtcs[name] = str(value)
            except (TimedOut, ValueError, AttributeError, TypeError):
                pass
        for c, name in connectors:
            if c == card:
                evidence.append(f"diagnostic: {card}-{name} CRTC {crtcs.get(name, 'unavailable')}")
    try:
        log = host.run(KERNEL_LOG)
        if log.returncode != 0:
            evidence.append("diagnostic: kernel log unavailable")
        lines = [line for line in log.stdout.splitlines() if re.search(r"apple[-_]dcp", line, re.I)
                 and re.search(r"mode|atomic", line, re.I)
                 and re.search(r"fail|error|not found|unknown|unable|cannot|could not|reject|invalid", line, re.I)] if log.returncode == 0 else []
        evidence.extend(f"diagnostic: kernel: {line}" for line in lines[-10:])
    except TimedOut:
        evidence.append("diagnostic: kernel log unavailable (timed out)")
    return evidence
