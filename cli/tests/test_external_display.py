"""External native modes: synthetic EDIDs and a read-only recorded desktop."""

from __future__ import annotations

import base64
import json
import os
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

from omarchy_m_test import external_display as display, host as host_module, monitor_rules, ports
from omarchy_m_test.host import MONITOR_INTENT, Bounded, bounded_read
from omarchy_m_test.privacy import Scrubber
from omarchy_m_test.recording import RECORDED_SOURCES, RecordedHost, RecordingHost, RecordingMiss
from tests.desktop import command
from tests.test_audio_display import run as run_section
from tests.live_mac import live_recording
from tests.test_interactive import check

HOME = "/home/tester"
CONFIG = f"{HOME}/.config/hypr/hyprland.conf"
DEFAULT = "monitor = , preferred, auto, auto\n"


def edid(width: int, height: int, refresh: float = 60) -> bytes:
    block = bytearray(128)
    block[:8] = b"\x00\xff\xff\xff\xff\xff\xff\x00"
    block[18:20] = bytes((1, 4))
    block[24] = 2
    hblank, vblank = 160, 40
    clock = round((width + hblank) * (height + vblank) * refresh / 10_000)
    block[54:56] = clock.to_bytes(2, "little")
    block[56:62] = bytes((width & 255, hblank & 255, ((width >> 8) << 4) | (hblank >> 8),
                          height & 255, vblank & 255, ((height >> 8) << 4) | (vblank >> 8)))
    block[127] = -sum(block) % 256
    return bytes(block)


def monitor(name="USB-1", width=3440, height=1440, **extra) -> dict:
    return {"id": 1, "name": name, "width": width, "height": height, "refreshRate": 60,
            "scale": 1, "transform": 0, "disabled": False, "mirrorOf": "none", **extra}


def fixture(monitors=None, preferred=None, config=DEFAULT) -> dict:
    monitors = [monitor()] if monitors is None else monitors
    preferred = preferred or {m["name"]: (m["width"], m["height"]) for m in monitors}
    connectors = "".join(f"connector card2-{name} connected enabled {w}x{h}\n" for name, (w, h) in preferred.items())
    files = {CONFIG: {"text": config}, f"{HOME}/.config/hypr/hyprland.lua": None,
             "/sys/kernel/debug/dri/2/state": None}
    for name, (width, height) in preferred.items():
        files[f"{display.DRM}/card2-{name}/edid"] = {"base64": base64.b64encode(edid(width, height)).decode()}
        files[f"{display.DRM}/card2-{name}/connector_id"] = {"text": "42\n"}
    return {"recording_version": 1, "env": {"HOME": HOME}, "files": files, "dirs": {}, "commands": [
        command(ports.DISPLAYS_LIST, connectors), command(display.MONITORS, json.dumps(monitors)),
        command(display.drm_info_argv("card2"), returncode=127), command(display.KERNEL_LOG),
    ]}


STOCK = os.path.join(os.path.dirname(__file__), "fixtures", "omarchy-hypr")  # Omarchy's current helpers, as shipped


def stock(name: str) -> str:
    with open(os.path.join(STOCK, f"{name}.lua"), encoding="utf-8") as f:
        return f.read()


HELPER_OPTIONAL, HELPER_ALL, HELPER_PATHS = stock("require_optional"), stock("require_all"), stock("paths")
BOOTSTRAP_LUA = 'dofile((os.getenv("OMARCHY_PATH") or "/usr/share/omarchy") .. "/default/hypr/bootstrap.lua")\n'
LUA = f"{HOME}/.config/hypr/hyprland.lua"
OMARCHY = "/usr/share/omarchy"


class NativeHost(RecordedHost):
    """Reads monitor rules itself; Lua module paths the fixture doesn't list are absent."""

    def monitor_intent(self, outputs):
        return monitor_rules.intent(self, outputs)

    def read_file(self, path):
        try:
            return super().read_file(path)
        except RecordingMiss:
            if path.startswith((f"{HOME}/.local/state/", f"{HOME}/.config/", f"{OMARCHY}/")) and path.endswith(".lua"):
                raise FileNotFoundError(path)
            raise


def lua(rec: dict, files: dict[str, str], main: str | None = None) -> dict:
    """Lua configuration: main is ~/.config/hypr/hyprland.lua, after Omarchy's bootstrap line unless it has its own;
    files are other paths (relative to $HOME). Omarchy's stock bootstrap is installed."""
    rec["files"][CONFIG] = None
    rec["files"].setdefault(f"{OMARCHY}/default/hypr/bootstrap.lua", {"text": stock("bootstrap")})
    if main is not None:
        rec["files"][LUA] = {"text": main if "bootstrap.lua" in main else BOOTSTRAP_LUA + main}
    for path, text in files.items():
        rec["files"][path if path.startswith("/") else f"{HOME}/{path}"] = {"text": text}
    return rec


def run(rec=None, cls=NativeHost):
    host = cls(rec or fixture())
    return display.check(types.SimpleNamespace(host=Bounded(host))), host


class NativeModeTest(unittest.TestCase):
    def test_native_passes_without_a_prompt_or_a_settle(self):
        result, host = run()
        self.assertEqual((result["id"], result["kind"], result["status"]), (display.CHECK_ID, "automatic", "pass"))
        self.assertIn("USB-1: current 3440x1440@60.00Hz, EDID preferred 3440x1440@60.00Hz", result["evidence"][1])
        self.assertEqual(host.slept, [])
        self.assertEqual(host.transcript, [])
        self.assertEqual(host.written, {})

    def test_two_outputs_stuck_at_their_shared_lower_mode_fail(self):
        rec = fixture([monitor(), monitor("USB-2", id=2)], {"USB-1": (3440, 1440), "USB-2": (3840, 2160)})
        for entry in rec["commands"]:
            if entry["argv"] == display.MONITORS:
                entry["stdout"] = json.dumps([monitor(width=2560), monitor("USB-2", 2560, 1440, id=2)])
        result, host = run(rec)
        self.assertEqual(result["status"], "fail")
        self.assertIn("USB-1: current 2560x1440@60.00Hz, EDID preferred 3440x1440@60.00Hz", result["evidence"][1])
        self.assertIn("USB-2: current 2560x1440@60.00Hz, EDID preferred 3840x2160@60.00Hz", result["evidence"][2])
        self.assertEqual(host.slept, [2])
        self.assertEqual(host.commands_run.count(display.MONITORS), 2)
        self.assertEqual(host.commands_run.count(ports.DISPLAYS_LIST), 2)

    def test_rotation_and_scale_do_not_change_mode_pixels(self):
        for transform in range(8):
            for scale in (1, 1.5, 2):
                with self.subTest(transform=transform, scale=scale):
                    result, _ = run(fixture([monitor(transform=transform, scale=scale)]))
                    self.assertEqual(result["status"], "pass")
        result, _ = run(fixture([monitor(width=2560, transform=1, scale=2)], {"USB-1": (3440, 1440)}))
        self.assertEqual(result["status"], "fail")

    def test_refresh_is_reported_only(self):
        result, _ = run(fixture([monitor(refreshRate=30)]))
        self.assertEqual(result["status"], "pass")
        self.assertIn("current 3440x1440@30.00Hz", result["evidence"][1])

    def test_identical_native_modes_are_not_a_failure(self):
        result, _ = run(fixture([monitor(), monitor("USB-2", id=2)]))
        self.assertEqual(result["status"], "pass")

    def test_hdmi_and_displayport_are_external_but_edp_is_not(self):
        for name in ("HDMI-A-1", "DP-1"):
            with self.subTest(name=name):
                result, _ = run(fixture([monitor(name)]))
                self.assertEqual(result["status"], "pass")
        result, host = run(fixture([monitor("eDP-1")]))
        self.assertEqual(result["status"], "skip")
        self.assertEqual(result["evidence"], ["skipped: no external display connected"])
        self.assertNotIn(display.MONITORS, host.commands_run)

    def test_no_external_display_skips(self):
        result, _ = run(fixture([]))
        self.assertEqual(result["status"], "skip")
        self.assertIn("no external display", result["evidence"][0])

    def test_bad_missing_and_unpreferred_edid_skip(self):
        good = edid(3440, 1440)
        bad_checksum = good[:-1] + bytes((good[-1] ^ 1,))
        for data in (None, b"", good[:80], bytes(128), bad_checksum, edid(0, 1440)):
            with self.subTest(data=data):
                rec = fixture()
                rec["files"][f"{display.DRM}/card2-USB-1/edid"] = None if data is None else {"base64": base64.b64encode(data).decode()}
                result, host = run(rec)
                self.assertEqual(result["status"], "skip")
                self.assertIn("EDID missing, unreadable", result["evidence"][1])
                self.assertEqual(host.slept, [])

    def test_edid_without_a_preferred_progressive_timing_is_not_guessed(self):
        for offset, value in ((24, 0), (54, 0), (71, 0x80)):
            block = bytearray(edid(3440, 1440))
            block[offset] = value
            if offset == 54:
                block[55] = 0
            block[127] = -sum(block[:127]) % 256
            self.assertIsNone(display.preferred_mode(bytes(block)))

    def test_unavailable_session_and_malformed_json_skip(self):
        for status, text in ((1, ""), (0, "{}"), (0, "invalid"), (0, '[{"width": 123}]')):
            rec = fixture()
            rec["commands"][1] = command(display.MONITORS, text, status)
            result, _ = run(rec)
            self.assertEqual(result["status"], "skip")
            self.assertIn("Hyprland session", result["evidence"][0])

    def test_a_transient_lower_mode_is_rechecked_and_passes(self):
        class Settling(NativeHost):
            def sleep(self, seconds):
                super().sleep(seconds)
                self.recording["commands"][1]["stdout"] = json.dumps([monitor()])

        rec = fixture([monitor(width=2560)], {"USB-1": (3440, 1440)})
        result, host = run(rec, Settling)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(host.slept, [2])
        self.assertIn("re-read after 2s settling", result["evidence"])

    def test_loss_of_session_while_settling_skips(self):
        class Gone(NativeHost):
            def sleep(self, seconds):
                super().sleep(seconds)
                self.recording["commands"][1]["returncode"] = 1

        result, _ = run(fixture([monitor(width=2560)], {"USB-1": (3440, 1440)}), Gone)
        self.assertEqual(result["status"], "skip")
        self.assertIn("state unavailable after settling", result["evidence"][0])

    def test_full_display_section_registers_and_classifies_the_automatic_check(self):
        rec = live_recording()
        fresh = fixture([monitor(width=2560)], {"USB-1": (3440, 1440)})
        fresh["commands"].append(command(MONITOR_INTENT, json.dumps(NativeHost(fresh).monitor_intent([{"name": "USB-1"}]))))
        rec["files"].update(fresh["files"])
        rec["env"].update(fresh["env"])
        for entry in fresh["commands"]:
            rec["commands"] = [old for old in rec["commands"] if old["argv"] != entry["argv"]] + [entry]
        host = run_section("display", ["s", "s", "s"], rec=rec)
        result = check(host, display.CHECK_ID)
        self.assertEqual((result["kind"], result["status"], result["classification"]["feature"]), ("automatic", "fail", "dcp"))


class MonitorIntentTest(unittest.TestCase):
    def test_explicit_fallback_named_and_description_rules_skip(self):
        for config in ("monitor = , 2560x1440@60, auto, 1\n",
                       DEFAULT + "monitor=USB-1,2560x1440,auto,1\n",
                       DEFAULT + "monitor=desc:Generic Ultrawide,2560x1440,auto,1\n"):
            with self.subTest(config=config):
                result, host = run(fixture([monitor(width=2560, description="Generic Ultrawide")],
                                           {"USB-1": (3440, 1440)}, config))
                self.assertEqual(result["status"], "skip")
                self.assertIn("explicit monitor mode", result["evidence"][1])
                self.assertEqual(host.slept, [])

    def test_named_preferred_overrides_explicit_fallback_and_last_rule_wins(self):
        config = "monitor=,2560x1440,auto,1\nmonitor=USB-1,2560x1440,auto,1\nmonitor=USB-1,preferred,auto,1\n"
        result, _ = run(fixture(config=config))
        self.assertEqual(result["status"], "pass")

    def test_mirrored_outputs_and_their_source_skip(self):
        rec = fixture([monitor(width=2560), monitor("USB-2", width=2560, id=2, mirrorOf="1")],
                      {"USB-1": (3440, 1440), "USB-2": (3840, 2160)})
        result, _ = run(rec)
        self.assertEqual(result["status"], "skip")
        self.assertTrue(all("mirroring" in line for line in result["evidence"][1:3]))
        result, _ = run(fixture(config=DEFAULT + "monitor=USB-1,preferred,auto,1,mirror,eDP-1\n"))
        self.assertEqual(result["status"], "skip")

    def test_disabled_outputs_skip(self):
        for config, monitors in (("monitor=USB-1,disable\n", []), (DEFAULT, [monitor(disabled=True)]),
                                 (DEFAULT, [monitor(dpmsStatus=False)])):
            result, _ = run(fixture(monitors, {"USB-1": (3440, 1440)}, config))
            self.assertEqual(result["status"], "skip")
            self.assertIn("disabled on purpose", result["evidence"][1])

    def test_static_sources_variables_and_commented_rules(self):
        rec = fixture(config=f"$screens = {HOME}/.config/hypr/screens\nsource = $screens/*.conf\n")
        directory = f"{HOME}/.config/hypr/screens"
        rec["dirs"][directory] = ["one.conf", "two.conf"]
        rec["files"][f"{directory}/one.conf"] = {"text": "monitor=USB-1,2560x1440,auto,1\n"}
        rec["files"][f"{directory}/two.conf"] = {"text": "# monitor=USB-1,2560x1440,auto,1\n" + DEFAULT + "monitor=USB-1,preferred,auto,1\n"}
        result, _ = run(rec)
        self.assertEqual(result["status"], "pass")

    def test_repeated_sources_follow_the_actual_last_rule(self):
        source = f"{HOME}/.config/hypr/modes.conf"
        rec = fixture(config=f"source={source}\nmonitor=USB-1,preferred,auto,1\nsource={source}\n")
        rec["files"][source] = {"text": "monitor=USB-1,2560x1440,auto,1\n"}
        result, _ = run(rec)
        self.assertEqual(result["status"], "skip")
        self.assertIn("explicit monitor mode", result["evidence"][1])

    def test_an_unreadable_source_or_cycle_leaves_intent_unknown(self):
        source = f"{HOME}/.config/hypr/modes.conf"
        for value in (None, {"text": f"source={CONFIG}\n"}):
            rec = fixture(config=DEFAULT + f"source={source}\n")
            rec["files"][source] = value
            result, _ = run(rec)
            self.assertEqual(result["status"], "skip")
            self.assertIn("mode intent unknown", result["evidence"][1])

    def test_a_skip_on_one_output_does_not_hide_a_downgrade_on_another(self):
        rec = fixture([monitor(width=2560), monitor("USB-2", width=2560, id=2)],
                      {"USB-1": (3440, 1440), "USB-2": (3840, 2160)}, DEFAULT + "monitor=USB-1,2560x1440,auto,1\n")
        result, _ = run(rec)
        self.assertEqual(result["status"], "fail")
        self.assertIn("explicit monitor mode", result["evidence"][1])
        self.assertIn("below preferred resolution", result["evidence"][2])

    def test_lua_monitor_rules_and_static_require(self):
        rec = lua(fixture(), {".config/hypr/monitors.lua": 'hl.monitor({ output = "USB-1", mode = "2560x1440@60", scale = 1 })\n'},
                  'require("hypr.monitors")\n')
        result, _ = run(rec)
        self.assertEqual(result["status"], "skip")
        self.assertIn("explicit monitor mode", result["evidence"][1])

    def test_lua_description_selectors_keep_quoted_commas_and_comment_characters(self):
        rec = fixture([monitor(width=2560, description="Generic, Inc. -- Display")], {"USB-1": (3440, 1440)})
        rec["files"][f"{HOME}/.config/hypr/hyprland.lua"] = {
            "text": 'hl.monitor { output = "desc:Generic, Inc. -- Display"; mode = "2560x1440"; scale = 1 }\n'}
        result, _ = run(rec)
        self.assertEqual(result["status"], "skip")
        self.assertIn("explicit monitor mode", result["evidence"][1])

    def test_omarchy_lua_bootstrap_and_a_static_preferred_rule_are_read_without_execution(self):
        rec = lua(fixture(), {}, BOOTSTRAP_LUA + 'require("hypr.monitors")\n')
        rec["files"][f"{HOME}/.config/hypr/monitors.lua"] = {
            "text": '-- hl.monitor { output="USB-1", mode="2560x1440" }\nhl.monitor { output="", mode="preferred", scale=omarchy_monitor_scale }\n'}
        result, _ = run(rec)
        self.assertEqual(result["status"], "pass")

    def test_computed_lua_rules_or_unreadable_config_skip(self):
        for text in ('hl.monitor({ output = "USB-1", mode = chosen_mode })', 'hl.monitor(screens[1])', None):
            rec = fixture()
            rec["files"][CONFIG] = None
            rec["files"][f"{HOME}/.config/hypr/hyprland.lua"] = {"text": text} if text else None
            result, _ = run(rec)
            self.assertEqual(result["status"], "skip")
            self.assertIn("mode intent unknown", result["evidence"][1])

    def test_monitorv2_fields_expand_variables(self):
        config = '$display = USB-1\nmonitorv2 {\n output = $display\n mode = 2560x1440@60\n}\n'
        result, _ = run(fixture([monitor(width=2560)], {"USB-1": (3440, 1440)}, config))
        self.assertIn("explicit monitor mode", result["evidence"][1])
        # with a preferred fallback too, which of the two wins isn't modelled: unknown, never a fail
        result, _ = run(fixture([monitor(width=2560)], {"USB-1": (3440, 1440)}, DEFAULT + config))
        self.assertIn("mode intent unknown", result["evidence"][1])
        config = DEFAULT + 'monitorv2 {\n output = $unset\n mode = 2560x1440@60\n}\n'
        result, _ = run(fixture([monitor(width=2560)], {"USB-1": (3440, 1440)}, config))
        self.assertIn("mode intent unknown", result["evidence"][1])

    def test_monitorv2_explicit_mode_skip(self):
        config = 'monitorv2 {\n output = USB-1\n mode = 2560x1440@60\n position = auto\n scale = 1\n}\n'
        result, _ = run(fixture(config=config))
        self.assertEqual(result["status"], "skip")
        self.assertIn("explicit monitor mode", result["evidence"][1])


class DiagnosticsTest(unittest.TestCase):
    def test_debugfs_and_kernel_failures_are_informational(self):
        rec = fixture()
        rec["files"]["/sys/kernel/debug/dri/2/state"] = {"text": "crtc[67]: crtc-1\n\tactive=1\nconnector[42]: USB-1\n\tcrtc=crtc-1\n"}
        rec["commands"][-1]["stdout"] = "apple-dcp 38bc00000.dcp: atomic check failed\napple-dcp: mode lookup failed for 2560x1440\napple-dcp: mode lookup succeeded\nunrelated: error\n"
        result, host = run(rec)
        self.assertEqual(result["status"], "pass")
        self.assertIn("diagnostic: card2-USB-1 CRTC 67", result["evidence"])
        self.assertEqual([line for line in result["evidence"] if "diagnostic: kernel:" in line],
                         ["diagnostic: kernel: apple-dcp: atomic-check-failed",
                          "diagnostic: kernel: apple-dcp: mode-not-found mode=2560x1440"])
        self.assertNotIn(display.drm_info_argv("card2"), host.commands_run)

    def test_drm_info_fallback_joins_by_connector_id(self):
        rec = fixture()
        rec["commands"][-2] = command(display.drm_info_argv("card2"), json.dumps({"/dev/dri/card2": {
            "connectors": [{"id": 41, "properties": {"CRTC_ID": {"value": 66}}},
                           {"id": 42, "properties": {"CRTC_ID": {"value": 67}}}]}}))
        result, _ = run(rec)
        self.assertEqual(result["status"], "pass")
        self.assertIn("diagnostic: card2-USB-1 CRTC 67", result["evidence"])

    def test_diagnostic_timeouts_and_malformed_json_do_not_change_a_result(self):
        for output, timeout in (("broken", 0), ("[]", 0), ("", 3)):
            rec = fixture()
            rec["commands"][-2] = {**command(display.drm_info_argv("card2"), output), "timed_out": timeout}
            rec["commands"][-1]["timed_out"] = 3
            result, _ = run(rec)
            self.assertEqual(result["status"], "pass")
            self.assertIn("diagnostic: card2-USB-1 CRTC unavailable", result["evidence"])


class RecordingTest(unittest.TestCase):
    def test_recorded_edid_replays_pass_and_fail_without_identity_or_descriptor_strings(self):
        for width in (3440, 2560):
            rec = fixture([monitor(width=width)], {"USB-1": (3440, 1440)})
            block = bytearray(edid(3440, 1440))
            block[8:18] = b"ID12345678"
            block[72:90] = b"\0\0\0\xff\0SYNTHETIC-ID\n"
            block[127] = -sum(block[:127]) % 256
            path = f"{display.DRM}/card2-USB-1/edid"
            rec["files"][path] = {"base64": base64.b64encode(block).decode()}
            recorder = RecordingHost(NativeHost(rec))
            result = display.check(types.SimpleNamespace(host=Bounded(recorder)))
            saved = recorder.recording(Scrubber())
            replayed, host = run(saved, RecordedHost)
            self.assertEqual(replayed, result)
            anonymous = host.read_file(path)
            self.assertEqual(display.preferred_mode(anonymous), display.preferred_mode(bytes(block)))
            self.assertEqual(anonymous[8:18], bytes(10))
            self.assertEqual(anonymous[72:126], bytes(54))
            self.assertEqual(sum(anonymous) % 256, 0)
            self.assertNotIn(b"SYNTHETIC-ID", anonymous)
            self.assertFalse(any("hyprland.conf" in path for path in saved["files"]))

    def test_invalid_edid_is_redacted_even_when_it_is_decodable_text(self):
        rec = fixture()
        path = f"{display.DRM}/card2-USB-1/edid"
        rec["files"][path] = {"text": "SYNTHETIC-ID"}
        recorder = RecordingHost(NativeHost(rec))
        result = display.check(types.SimpleNamespace(host=Bounded(recorder)))
        saved = recorder.recording(Scrubber())
        self.assertEqual(saved["files"][path], {"redacted_bytes": 12})
        self.assertEqual(run(saved, RecordedHost)[0], result)


def synthetic_identity_monitor(**extra) -> dict:
    return monitor(make="SYNTHMAKE", model="SYNTHMODEL", description="SYNTHMAKE SYNTHMODEL SYNTHSERIAL",
                   serial="SYNTHSERIAL", activeWorkspace={"name": "SYNTHWS"}, availableModes=["3440x1440@60.00Hz", "SYNTH"],
                   **extra)


def record(rec: dict, cls=NativeHost) -> tuple[dict, dict, RecordingHost]:
    """Run the check live through record mode; the result and the saved (scrubbed) recording."""
    recorder = RecordingHost(cls(rec))
    result = display.check(types.SimpleNamespace(host=Bounded(recorder)))
    return result, recorder.recording(Scrubber()), recorder


class RecordedProjectionTest(unittest.TestCase):
    """Review finding 1: recordings keep an allowlisted projection, never monitor identity."""

    def test_hyprctl_monitors_keep_only_names_modes_flags_and_ids(self):
        rec = fixture([synthetic_identity_monitor()])
        rec["commands"][1]["stderr"] = "SYNTHMODEL warning\n"
        result, saved, _ = record(rec)
        entry = next(e for e in saved["commands"] if e["argv"] == display.MONITORS)
        self.assertNotIn("SYNTH", json.dumps(entry))
        self.assertEqual(json.loads(entry["stdout"]), [{
            "name": "USB-1", "id": 1, "width": 3440, "height": 1440, "refreshRate": 60.0, "transform": 0, "scale": 1.0,
            "disabled": False, "mirrorOf": "none", "availableModes": ["3440x1440@60.00Hz"]}])
        self.assertEqual(run(saved, RecordedHost)[0], result)

    def test_a_serial_named_only_by_hyprctl_is_still_scrubbed_elsewhere(self):
        rec = fixture([monitor(serial="9RKXZN3")])
        rec["commands"].append(command(RECORDED_SOURCES[0], "Oct 03 kernel: usb 1-1: display disconnected: 9RKXZN3\n"))
        recorder = RecordingHost(NativeHost(rec))
        display.check(types.SimpleNamespace(host=Bounded(recorder)))
        recorder.capture_sources([RECORDED_SOURCES[0]])
        self.assertNotIn("9RKXZN3", json.dumps(recorder.recording(Scrubber())))

    def test_an_output_name_that_is_not_a_connector_is_dropped(self):
        self.assertEqual(json.loads(display.recorded_output(display.MONITORS, json.dumps([monitor("SYNTHMODEL-1")]), "")[0]), [])
        self.assertEqual(display.recorded_output(display.MONITORS, "not json SYNTH", "")[0], "")

    def test_debugfs_state_and_drm_info_keep_numeric_connector_and_crtc_ids(self):
        rec = fixture()
        rec["files"]["/sys/kernel/debug/dri/2/state"] = {"text": (
            "plane[31]: plane-0\n\tfb=99\n\t\tallocated by = SYNTHPROC\ncrtc[67]: crtc-1\n\tactive=1\n\tmode: \"SYNTHMODE\"\n"
            "connector[42]: USB-1\n\tcrtc=crtc-1\n\tself_refresh_aware=0\n\tSYNTHSERIAL\n")}
        result, saved, _ = record(rec)
        state = saved["files"]["/sys/kernel/debug/dri/2/state"]["text"]
        self.assertEqual(state, "crtc[67]: crtc-1\nconnector[42]: USB-1\n\tcrtc=crtc-1\n")
        self.assertEqual(run(saved, RecordedHost)[0], result)
        self.assertIn("diagnostic: card2-USB-1 CRTC 67", result["evidence"])

        info = {"/dev/dri/card2": {"driver": {"name": "SYNTH"}, "connectors": [
            {"id": 42, "name": "SYNTHMODEL", "modes": [{"name": "SYNTH"}],
             "properties": {"CRTC_ID": {"value": 67}, "EDID": {"value": "SYNTHSERIAL"}}}]}}
        rec = fixture()
        rec["commands"][2] = command(display.drm_info_argv("card2"), json.dumps(info), stderr="SYNTH\n")
        result, saved, _ = record(rec)
        entry = next(e for e in saved["commands"] if e["argv"] == display.drm_info_argv("card2"))
        self.assertNotIn("SYNTH", json.dumps(entry))
        self.assertEqual(json.loads(entry["stdout"]), {"/dev/dri/card2": {"connectors": [{"id": 42, "properties": {"CRTC_ID": {"value": 67}}}]}})
        self.assertEqual(run(saved, RecordedHost)[0], result)
        self.assertIn("diagnostic: card2-USB-1 CRTC 67", result["evidence"])


class KernelDiagnosticTest(unittest.TestCase):
    """Review finding 2: apple-dcp findings are fixed categories with validated numbers, never message text."""

    LOG = ("apple-dcp 38bc00000.dcp: atomic check failed for SYNTHMODEL\n"
           "apple-dcp 38bc00000.dcp: set_digital_out_mode finished:-22 SYNTHSERIAL\n"
           "apple-dcp 38bc00000.dcp: set_digital_out_mode finished:8338\n"
           "apple-dcp 38bc00000.dcp: swap failed! status 3\n"
           "apple-dcp 38bc00000.dcp: swap failed! status 3\n"
           "apple-dcp 38bc00000.dcp: dcp_dptx_connect: port 1 link complete failed:-110\n"
           "apple-dcp 38bc00000.dcp: SYNTHMODEL mode on DP-1 rejected\n"
           "apple-dcp 38bc00000.dcp: cb_hotplug() connected:1, valid_mode:0\n")

    def test_reports_carry_categories_and_numbers_only(self):
        rec = fixture()
        rec["commands"][-1]["stdout"] = self.LOG
        result, _ = run(rec)
        kernel = [line for line in result["evidence"] if "kernel:" in line]
        self.assertEqual(kernel, [
            "diagnostic: kernel: apple-dcp: atomic-check-failed",
            "diagnostic: kernel: apple-dcp: mode-set-failed errno=-22",
            "diagnostic: kernel: apple-dcp: swap-failed status=3 (x2)",
            "diagnostic: kernel: apple-dcp: link-failed errno=-110 port=1",
            "diagnostic: kernel: apple-dcp: mode-failed",
        ])
        self.assertNotIn("SYNTH", json.dumps(result))

    def test_out_of_range_numbers_are_dropped(self):
        self.assertEqual(display.dcp_finding("apple-dcp x: swap failed! status 99999999999"), "apple-dcp: swap-failed")
        self.assertEqual(display.dcp_finding("apple-dcp x: mode 99999x1 not found"), "apple-dcp: mode-not-found")

    def test_recordings_keep_the_canonical_findings_and_replay_the_same_evidence(self):
        rec = fixture()
        rec["commands"][-1]["stdout"] = self.LOG
        dmesg = "Oct 03 kernel: " + self.LOG.replace("\n", "\nOct 03 kernel: ").rstrip("Oct 03 kernel: ") + "Oct 03 kernel: usb 1-1: new device\n"
        rec["commands"].append(command(RECORDED_SOURCES[0], dmesg))
        recorder = RecordingHost(NativeHost(rec))
        result = display.check(types.SimpleNamespace(host=Bounded(recorder)))
        recorder.capture_sources([RECORDED_SOURCES[0]])
        saved = recorder.recording(Scrubber())
        self.assertNotIn("SYNTH", json.dumps(saved))
        full = next(e for e in saved["commands"] if e["argv"] == RECORDED_SOURCES[0])["stdout"]
        self.assertIn("Oct 03 kernel: apple-dcp: swap-failed status=3\n", full)
        self.assertIn("usb 1-1: new device", full)
        self.assertIn("set_digital_out_mode finished:8338", full)  # not a finding: kept as it was
        self.assertEqual(run(saved, RecordedHost)[0], result)


class LiteralLuaRulesTest(unittest.TestCase):
    """Review finding 3: only fully literal Lua rules count; anything computed or conditional leaves intent unknown."""

    def assert_unknown(self, rec):
        result, _ = run(rec)
        self.assertEqual(result["status"], "skip")
        self.assertIn("mode intent unknown", result["evidence"][1])

    def lower(self):
        return fixture([monitor(width=2560)], {"USB-1": (3440, 1440)})

    def test_computed_selectors_and_modes_skip_instead_of_failing(self):
        for text in ('hl.monitor { output="USB" .. "-1", mode="2560x1440" }',
                     'hl.monitor { output=name, mode="2560x1440" }',
                     'hl.monitor { output="USB-1", mode=pick("2560x1440") }',
                     'hl.monitor { output="USB-1", mode="2560" .. "x1440" }',
                     'hl.monitor { output="USB-\\x31", mode="2560x1440" }',
                     'hl.monitor { output=[[USB-1]], mode="2560x1440" }',
                     'hl.monitor { "USB-1", "2560x1440" }',
                     'hl.monitor { ["output"]="USB-1", mode="2560x1440" }',
                     'hl.monitor({ output="USB-1" }, extra)',
                     'local m = hl.monitor\nm { output="USB-1", mode="2560x1440" }',
                     'local h = hl\nh.monitor { output="USB-1", mode="2560x1440" }',
                     'hl["monitor"] { output="USB-1", mode="2560x1440" }',
                     'if wide then hl.monitor { output="USB-1", mode="2560x1440" } end',
                     'local function f() hl.monitor { output="USB-1", mode="2560x1440" } end',
                     'local _ = wide and hl.monitor { output="USB-1", mode="2560x1440" }',
                     '_G.hl.monitor { output="USB-1", mode=wide }',
                     'local g = _G\ng.hl.monitor { output="USB-1", mode="2560x1440" }'):
            with self.subTest(text=text):
                self.assert_unknown(lua(self.lower(), {}, DEFAULT_LUA + text + "\n"))

    def test_a_literal_rule_still_counts_and_computed_scale_does_not_matter(self):
        rec = lua(self.lower(), {}, DEFAULT_LUA + 'hl.monitor { output = "USB-1", mode = "preferred", scale = omarchy_scale }\n')
        self.assertEqual(run(rec)[0]["status"], "fail")
        rec = lua(self.lower(), {}, 'hl.monitor { output = "USB-1", mode = "2560x1440", scale = 1.5 * 2 }\n')
        self.assertIn("explicit monitor mode", run(rec)[0]["evidence"][1])

    def test_conditional_or_computed_requires(self):
        rules = {".config/hypr/modes.lua": 'hl.monitor { output="USB-1", mode="2560x1440" }\n'}
        rules[f"{OMARCHY}/default/hypr/require_optional.lua"] = HELPER_OPTIONAL
        for main in ('if wide then require("hypr.modes") end\n',
                     'local ok = pcall(require, "hypr.modes")\n',
                     'local name = "hypr.modes"\nrequire(name)\n',
                     'require("hypr." .. "modes")\n',
                     'local _ = wide or require("hypr.modes")\n',
                     'for _, m in ipairs(list) do require("hypr.modes") end\n',
                     OPTIONAL + 'require_optional.module("hypr.modes")\n',
                     'require_optional.module("hypr.keys")\n',  # not bound to Omarchy's helper here
                     'dofile("/home/tester/.config/hypr/modes.lua")\n',
                     'package.path = somewhere .. package.path\n'):
            with self.subTest(main=main):
                self.assert_unknown(lua(self.lower(), rules, DEFAULT_LUA + main))

    def test_an_unconditional_literal_require_is_followed(self):
        rec = lua(self.lower(), {".config/hypr/modes.lua": 'hl.monitor { output="USB-1", mode="2560x1440" }\n'},
                  DEFAULT_LUA + 'local modes = require("hypr.modes")\n')
        self.assertIn("explicit monitor mode", run(rec)[0]["evidence"][1])

    def test_a_conditional_load_without_monitor_rules_does_not_matter(self):
        rec = lua(self.lower(), {".config/hypr/keys.lua": 'hl.bind("SUPER", "Q", "killactive")\n',
                                 f"{OMARCHY}/default/hypr/require_optional.lua": HELPER_OPTIONAL},
                  DEFAULT_LUA + OPTIONAL + 'if _G.bindings ~= false then\n  require("hypr.keys")\nend\n'
                  + 'require_optional.module("omarchy.current.theme.hyprland")\n')
        self.assertEqual(run(rec)[0]["status"], "fail")

    def test_omarchy_loaders_resolve_statically(self):
        state = f"{HOME}/.local/state/omarchy/toggles/hypr"
        files = {
            f"{OMARCHY}/default/hypr/omarchy.lua": 'local require_optional = require("default.hypr.require_optional")\nrequire("default.hypr.toggles")\n'
                                                   'require_optional.module("omarchy.current.theme.hyprland")\n',
            f"{OMARCHY}/default/hypr/require_optional.lua": HELPER_OPTIONAL,
            f"{OMARCHY}/default/hypr/require_all.lua": HELPER_ALL,
            f"{OMARCHY}/default/hypr/paths.lua": HELPER_PATHS,
            f"{OMARCHY}/default/hypr/toggles.lua": 'local paths = require("default.hypr.paths")\nlocal require_all = require("default.hypr.require_all")\n'
                                                   'local toggles_dir = paths.state_home .. "/omarchy/toggles/hypr"\n'
                                                   'package.path = toggles_dir .. "/?.lua;" .. package.path\n'
                                                   'require_all.files(toggles_dir, nil, { reload = true, exclude = { ["legacy"] = true } })\n',
            f"{state}/flags.lua": "hl.config({ general = { gaps_in = 0 } })\n",
            f"{state}/legacy.lua": 'hl.monitor { output="USB-1", mode="2560x1440" }\n',
        }
        main = BOOTSTRAP_LUA + 'require("default.hypr.omarchy")\nrequire("hypr.monitors")\n'
        rec = lua(self.lower(), {**files, ".config/hypr/monitors.lua": 'hl.monitor { output="", mode="preferred", scale=s }\n'}, main)
        rec["dirs"][state] = ["flags.lua", "legacy.lua", "notes.txt"]
        result, _ = run(rec)
        self.assertEqual(result["status"], "fail")  # the excluded legacy file's rule is not read
        # a toggle that does set a rule is read as an unconditional load
        rec["dirs"][state] = ["flags.lua", "wide.lua"]
        rec["files"][f"{state}/wide.lua"] = {"text": 'hl.monitor { output="USB-1", mode="2560x1440" }\n'}
        self.assertIn("explicit monitor mode", run(rec)[0]["evidence"][1])
        # an unresolvable directory is unknown
        rec["files"][f"{OMARCHY}/default/hypr/toggles.lua"] = {"text": 'local require_all = require("default.hypr.require_all")\nrequire_all.files(os.getenv("X"))\n'}
        self.assert_unknown(rec)

    def test_a_conditional_theme_with_monitor_rules_is_unknown(self):
        rec = lua(self.lower(), {".config/omarchy/current/theme/hyprland.lua": 'hl.monitor { output="USB-1", mode="preferred" }\n'},
                  DEFAULT_LUA + OPTIONAL + 'require_optional.module("omarchy.current.theme.hyprland")\n')
        rec["files"][f"{OMARCHY}/default/hypr/require_optional.lua"] = {"text": HELPER_OPTIONAL}
        self.assert_unknown(rec)
        rec["files"].pop(f"{HOME}/.config/omarchy/current/theme/hyprland.lua")
        self.assertEqual(run(rec)[0]["status"], "fail")  # a missing optional theme is harmless

    def test_a_statement_that_branches_across_lines_is_conditional(self):
        modes = {".config/hypr/modes.lua": 'hl.monitor { output="USB-1", mode="2560x1440" }\n'}
        for main in ('hl.monitor { output="USB-1", mode="2560x1440" }\nlocal x = false and\n  hl.monitor { output="USB-1", mode="preferred" }\n',
                     'local x = ready\n  or require("hypr.modes")\n',
                     'local x = (ready or\n  require("hypr.modes"))\n'):
            with self.subTest(main=main):
                self.assert_unknown(lua(self.lower(), modes, DEFAULT_LUA + main))
        # a branch that ended doesn't make the next statement conditional
        rec = lua(self.lower(), modes, DEFAULT_LUA + 'local x = a or b\nrequire("hypr.modes")\n')
        self.assertIn("explicit monitor mode", run(rec)[0]["evidence"][1])

    def test_a_rebound_directory_or_helper_is_not_trusted(self):
        hypr = f"{HOME}/.config/hypr"
        for main in (ALL + f'local dir = "{hypr}/old"\ndir = "{hypr}/new"\nrequire_all.files(dir, "hypr.new")\n',
                     ALL + f'local dir = "{hypr}/old"\nfor _, dir in ipairs(list) do require_all.files(dir, "hypr.new") end\n',
                     ALL + f'local dir = "{hypr}/old"\nlocal dir, other = "{hypr}/new", 1\nrequire_all.files(dir, "hypr.new")\n',
                     ALL + f'local dir = "{hypr}/old"\nlocal function load(dir) require_all.files(dir, "hypr.new") end\n',
                     ALL + 'require_all = mine\nrequire_all.files("/x", "y")\n'):
            with self.subTest(main=main):
                rec = lua(self.lower(), {".config/hypr/new/wide.lua": 'hl.monitor { output="USB-1", mode="2560x1440" }\n'}, DEFAULT_LUA + main)
                rec["files"][f"{OMARCHY}/default/hypr/require_all.lua"] = {"text": HELPER_ALL}
                rec["dirs"][f"{hypr}/old"] = []
                rec["dirs"][f"{hypr}/new"] = ["wide.lua"]
                self.assert_unknown(rec)

    def test_a_changed_helper_body_is_not_trusted(self):
        rec = lua(self.lower(), {}, DEFAULT_LUA + OPTIONAL)
        rec["files"][f"{HOME}/.config/hypr/modes.lua"] = {"text": 'hl.monitor { output="USB-1", mode="2560x1440" }\n'}
        for body in (HELPER_OPTIONAL + 'hl.monitor { output="USB-1", mode="2560x1440" }\n',
                     HELPER_OPTIONAL.replace("return M", 'local module = "hypr.modes"\nrequire(module)\nreturn M'),
                     HELPER_OPTIONAL + 'dofile("/x.lua")\n'):
            with self.subTest(body=body):
                rec["files"][f"{OMARCHY}/default/hypr/require_optional.lua"] = {"text": body}
                self.assert_unknown(rec)
        rec["files"][f"{OMARCHY}/default/hypr/require_optional.lua"] = {"text": HELPER_OPTIONAL}
        self.assertEqual(run(rec)[0]["status"], "fail")

    def test_a_helper_value_that_is_written_aliased_or_indexed_is_not_trusted(self):
        hypr = f"{HOME}/.config/hypr"
        paths = 'local paths = require("default.hypr.paths")\n'
        for main in (paths + ALL + 'paths.config_home = "/new"\nrequire_all.files(paths.config_home .. "/hypr/new", "hypr.new")\n',
                     paths + ALL + 'local p = paths\np.config_home = "/new"\nrequire_all.files(paths.config_home .. "/hypr/new", "hypr.new")\n',
                     paths + ALL + 'paths["config_home"] = "/new"\nrequire_all.files(paths.config_home .. "/hypr/new", "hypr.new")\n',
                     ALL + 'require("default.hypr.paths").config_home = "/new"\n',
                     ALL + '(require("default.hypr.paths")).config_home = "/new"\n',
                     paths + ALL + 'paths.config_home, x = "/new", 1\nrequire_all.files(paths.config_home .. "/hypr/new", "hypr.new")\n',
                     ALL + 'require_all.files = nil\n',
                     'package.loaded["default.hypr.paths"] = { config_home = "/new" }\n'):
            with self.subTest(main=main):
                rec = lua(self.lower(), {f"{OMARCHY}/default/hypr/paths.lua": HELPER_PATHS,
                                         f"{OMARCHY}/default/hypr/require_all.lua": HELPER_ALL,
                                         "/new/hypr/new/wide.lua": 'hl.monitor { output="USB-1", mode="2560x1440" }\n'}, DEFAULT_LUA + main)
                rec["dirs"][f"{hypr}/new"] = []
                rec["dirs"]["/new/hypr/new"] = ["wide.lua"]
                self.assert_unknown(rec)
        # reading the helpers as shipped resolves the directory
        rec = lua(self.lower(), {f"{OMARCHY}/default/hypr/paths.lua": HELPER_PATHS, f"{OMARCHY}/default/hypr/require_all.lua": HELPER_ALL,
                                 ".config/hypr/new/wide.lua": 'hl.monitor { output="USB-1", mode="2560x1440" }\n'},
                  DEFAULT_LUA + paths + ALL + 'require_all.files(paths.config_home .. "/hypr/new", "hypr.new")\n')
        rec["dirs"][f"{hypr}/new"] = ["wide.lua"]
        self.assertIn("explicit monitor mode", run(rec)[0]["evidence"][1])

    def test_truncated_or_bootstrap_only_configuration_does_not_crash(self):
        rec = lua(self.lower(), {}, BOOTSTRAP_LUA)
        self.assertEqual(run(rec)[0]["status"], "fail")  # no rule: Hyprland's preferred default
        for main in ('package.path = "/?.lua;" .. package.path\n', 'require', 'hl.monitor', 'require_all.files',
                     'local x =', 'dofile('):
            with self.subTest(main=main):
                self.assert_unknown(lua(self.lower(), {}, main))

    def test_an_unprefixed_directory_load_resolves_through_package_path(self):
        files = {f"{OMARCHY}/default/hypr/require_all.lua": HELPER_ALL,
                 "/listed/wide.lua": 'hl.monitor { output="USB-1", mode="preferred" }\n',
                 ".config/wide.lua": 'hl.monitor { output="USB-1", mode="2560x1440" }\n'}
        rec = lua(self.lower(), files, DEFAULT_LUA + ALL + 'require_all.files("/listed")\n')
        rec["dirs"]["/listed"] = ["wide.lua"]
        self.assertIn("explicit monitor mode", run(rec)[0]["evidence"][1])  # require("wide") finds ~/.config/wide.lua
        rec = lua(rec, {}, DEFAULT_LUA + ALL + 'package.path = "/listed" .. "/?.lua;" .. package.path\nrequire_all.files("/listed")\n')
        self.assertEqual(run(rec)[0]["status"], "fail")  # with the directory first on package.path, its own file

    def test_what_an_ignored_field_runs_still_counts(self):
        for field in ('scale = (function() hl.monitor { output="USB-1", mode="2560x1440" } return 1 end)()',
                      'scale = pcall(require, "hypr.modes")', 'scale = load("x")()'):
            with self.subTest(field=field):
                self.assert_unknown(lua(self.lower(), {}, 'hl.monitor { output = "", mode = "preferred", ' + field + ' }\n'))

    def test_a_helper_bound_in_another_form_is_not_followed(self):
        hypr = f"{HOME}/.config/hypr"
        for binding in ('local ra, unused = require("default.hypr.require_all"), nil\n',
                        'ra = require("default.hypr.require_all")\n', 'local ra = (require("default.hypr.require_all"))\n',
                        'require("default.hypr.require_all")\n'):
            with self.subTest(binding=binding):
                rec = lua(self.lower(), {f"{OMARCHY}/default/hypr/require_all.lua": HELPER_ALL,
                                         ".config/hypr/new/wide.lua": 'hl.monitor { output="USB-1", mode="2560x1440" }\n'},
                          DEFAULT_LUA + binding + f'ra.files("{hypr}/new", "hypr.new")\n')
                rec["dirs"][f"{hypr}/new"] = ["wide.lua"]
                self.assert_unknown(rec)
        for binding in ('local ra = require "default.hypr.require_all"\n', 'local ra = require("default.hypr.require_all");\n'):
            with self.subTest(binding=binding):
                rec["files"][LUA] = {"text": BOOTSTRAP_LUA + DEFAULT_LUA + binding + f'ra.files("{hypr}/new", "hypr.new")\n'}
                self.assertIn("explicit monitor mode", run(rec)[0]["evidence"][1])  # these bind too
        for binding in ('local ra = require("default.hypr.require_all")\n  and { files = function() end }\n',
                        'local ra = require("default.hypr.require_all")\n  .files\n', 'local ra = require(\n"default.hypr.require_all")\n',
                        'local ra = require("default.hypr.require_all")\n("x")\n'):
            with self.subTest(binding=binding):
                rec["files"][LUA] = {"text": BOOTSTRAP_LUA + DEFAULT_LUA + binding + f'ra.files("{hypr}/new", "hypr.new")\n'}
                self.assert_unknown(rec)

    def test_a_directory_load_lists_regular_files_only(self):
        files = {f"{OMARCHY}/default/hypr/require_all.lua": HELPER_ALL,
                 ".config/wide.lua": 'hl.monitor { output="USB-1", mode="preferred" }\n'}
        rec = lua(self.lower(), files, 'hl.monitor { output="USB-1", mode="2560x1440" }\n' + ALL + 'require_all.files("/listed")\n')
        rec["dirs"]["/listed"] = ["wide.lua"]
        rec["regular_files"] = {"/listed": []}  # wide.lua there is a directory or a symlink: find -type f skips it
        self.assertIn("explicit monitor mode", run(rec)[0]["evidence"][1])
        with tempfile.TemporaryDirectory() as directory:
            os.mkdir(os.path.join(directory, "dir.lua"))
            os.symlink(os.path.join(directory, "file.lua"), os.path.join(directory, "link.lua"))
            with open(os.path.join(directory, "file.lua"), "w") as f:
                f.write("\n")
            self.assertEqual(host_module.RealHost().regular_files(directory), ["file.lua"])
            os.symlink(directory, os.path.join(directory, "linked"))
            self.assertEqual(host_module.RealHost().regular_files(os.path.join(directory, "linked")), [])

    def test_a_package_path_change_that_goes_on_is_unknown(self):
        rec = lua(self.lower(), {"/lower/wide.lua": 'hl.monitor { output="USB-1", mode="2560x1440" }\n',
                                 "/pref/wide.lua": 'hl.monitor { output="USB-1", mode="preferred" }\n'},
                  DEFAULT_LUA + 'package.path = "/pref" .. "/?.lua;" .. package.path\n  and "/lower/?.lua"\nrequire("wide")\n')
        self.assert_unknown(rec)

    def test_a_directory_is_used_as_written(self):
        with tempfile.TemporaryDirectory() as directory:
            real = os.path.join(directory, "real")
            os.mkdir(real)
            with open(os.path.join(real, "wide.lua"), "w") as f:
                f.write('hl.monitor { output="USB-1", mode="2560x1440" }\n')
            os.symlink(real, os.path.join(directory, "link"))
            main = DEFAULT_LUA + ALL + f'package.path = "{directory}/link/" .. "/?.lua;" .. package.path\nrequire_all.files("{directory}/link/")\n'

            class Host(NativeHost):
                def regular_files(self, path):
                    return host_module.RealHost().regular_files(path)

                def read_file(self, path):
                    return bounded_read(path) if path.startswith(directory) else super().read_file(path)

            rec = lua(self.lower(), {f"{OMARCHY}/default/hypr/require_all.lua": HELPER_ALL}, main)
            result, _ = run(rec, Host)
            self.assertIn("explicit monitor mode", result["evidence"][1])  # "link/" is followed, as find follows it

    def test_a_module_is_loaded_once(self):
        rec = lua(self.lower(), {".config/hypr/keys.lua": 'hl.bind("SUPER", "Q", "killactive")\n'},
                  DEFAULT_LUA + 'require("hypr.keys")\nrequire("hypr.keys")\n')
        self.assertEqual(run(rec)[0]["status"], "fail")
        # requiring a module with rules again (cached, or reloaded when it returned false) isn't modelled
        rec = lua(self.lower(), {".config/hypr/modes.lua": 'hl.monitor { output="USB-1", mode="2560x1440" }\nreturn false\n'},
                  'require("hypr.modes")\nhl.monitor { output="USB-1", mode="preferred" }\nrequire("hypr.modes")\n')
        self.assert_unknown(rec)

    def test_control_flow_cache_and_order_effects_are_unknown(self):
        modes = {".config/hypr/modes.lua": 'hl.monitor { output="USB-1", mode="2560x1440" }\n',
                 ".config/hypr/pref.lua": 'hl.monitor { output="USB-1", mode="preferred" }\n'}
        for main in ('goto skip\nhl.monitor { output="USB-1", mode="2560x1440" }\n::skip::\n',
                     'if ready then return end\nrequire("hypr.modes")\n',
                     BOOTSTRAP_LUA + BOOTSTRAP_LUA,
                     'if x then package.path = "/x" .. "/?.lua;" .. package.path end\n',
                     'hl.monitor { output="USB-1", mode="2560x1440", scale=require("hypr.pref") }\n',
                     'hl.monitor { output="USB-1", mode="2560x1440", scale=f"x" }\n',
                     ALL + 'require_all.files("/x", "y", { exclude = { a = true }, exclude = { b = true } })\n',
                     ALL + 'require_all.files("/x", "y", { reload = true, reload = false })\n',
                     'local ra = require("default.hypr.require_all")\nlocal ra = require("default.hypr.require_all")\nra.files("/x", "y")\n'):
            with self.subTest(main=main):
                rec = lua(self.lower(), {**modes, f"{OMARCHY}/default/hypr/require_all.lua": HELPER_ALL}, DEFAULT_LUA + main)
                self.assert_unknown(rec)
        rec = lua(self.lower(), {}, 'require("missing")\n')
        rec["files"][LUA] = {"text": 'hl.monitor { output="USB-1", mode="preferred" }\nrequire("hypr.modes")\n'}
        self.assert_unknown(rec)  # no bootstrap: where modules are found isn't known
        rec = lua(self.lower(), {}, DEFAULT_LUA)
        rec["files"][f"{OMARCHY}/default/hypr/bootstrap.lua"] = {"text": stock("bootstrap") + "\npackage.path = '/x/?.lua'\n"}
        self.assert_unknown(rec)  # a changed bootstrap

    def test_hyprlang_constructs_this_reader_cant_follow_are_unknown(self):
        for config in (DEFAULT + "# hyprlang if WIDE\nmonitor=USB-1,2560x1440,auto,1\n# hyprlang endif\n",
                       DEFAULT + "monitor=USB-1,2560x1440,auto,{{1+1}}\n",
                       DEFAULT + "monitor=USB-1,\\\n2560x1440,auto,1\n",
                       DEFAULT + "$m = monitor\n${m} = USB-1,2560x1440,auto,1\n",
                       DEFAULT + "general {\n  monitor = USB-1,2560x1440,auto,1\n}\n",
                       DEFAULT + "exec = echo ## monitor=USB-1,2560x1440\n",
                       DEFAULT + "monitorv2[x] {\n output = USB-1\n}\n",
                       DEFAULT + "general {\n"):
            with self.subTest(config=config):
                result, _ = run(self.lower_conf(config))
                self.assertEqual(result["status"], "skip")
        # Omarchy's own: a noerror directive, ## in a comment line, a glob over a missing directory
        rec = self.lower_conf("# hyprlang noerror true\n# type # as ## here\n" + DEFAULT
                              + f"source = {HOME}/.local/state/omarchy/toggles/hypr/*.conf\n# hyprlang noerror false\n")
        rec["dirs"][f"{HOME}/.local/state/omarchy/toggles/hypr"] = None
        self.assertEqual(run(rec)[0]["status"], "fail")
        # quoted text naming monitorv2 in another key is just text
        result, _ = run(self.lower_conf(DEFAULT + 'exec = echo "monitorv2 { output = USB-1 mode = 2560x1440 }"\n'))
        self.assertEqual(result["status"], "fail")

    def test_hyprlang_variables_carry_into_sources_and_globs_skip_hidden_files(self):
        hypr = f"{HOME}/.config/hypr"
        rec = self.lower_conf(f"$screen = USB-1\nsource = {hypr}/conf.d/*.conf\n")
        rec["dirs"][f"{hypr}/conf.d"] = [".hidden.conf", "a.conf"]
        rec["files"][f"{hypr}/conf.d/a.conf"] = {"text": DEFAULT + "monitor=$screen,2560x1440,auto,1\n"}
        rec["files"][f"{hypr}/conf.d/.hidden.conf"] = {"text": "monitor=$screen,preferred,auto,1\n"}
        self.assertIn("explicit monitor mode", run(rec)[0]["evidence"][1])

    def test_a_description_selector_may_have_a_space_after_desc(self):
        rec = fixture([monitor(width=2560, description="Generic Ultrawide")], {"USB-1": (3440, 1440)},
                      DEFAULT + "monitor=desc: Generic Ultrawide,2560x1440,auto,1\n")
        self.assertIn("explicit monitor mode", run(rec)[0]["evidence"][1])

    def lower_conf(self, config):
        return fixture([monitor(width=2560)], {"USB-1": (3440, 1440)}, config)


OPTIONAL = 'local require_optional = require("default.hypr.require_optional")\n'
ALL = 'local require_all = require("default.hypr.require_all")\n'
DEFAULT_LUA = 'hl.monitor({ output = "", mode = "preferred", position = "auto", scale = 1 })\n'


class BoundedReadTest(unittest.TestCase):
    """Review finding 4: reads refuse non-regular files and are bounded in size and time."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def test_a_fifo_or_directory_is_refused_at_once(self):
        fifo = os.path.join(self.dir.name, "fifo")
        os.mkfifo(fifo)
        for path in (fifo, self.dir.name):
            started = time.monotonic()
            with self.assertRaises(OSError) as raised:
                bounded_read(path)
            self.assertNotIsInstance(raised.exception, FileNotFoundError)
            self.assertLess(time.monotonic() - started, 1)

    def test_size_cap_and_regular_reads(self):
        path = os.path.join(self.dir.name, "big")
        with open(path, "wb") as f:
            f.write(b"x" * 100)
        self.assertEqual(bounded_read(path, limit=100), b"x" * 100)
        with self.assertRaises(OSError):
            bounded_read(path, limit=99)
        with self.assertRaises(FileNotFoundError):
            bounded_read(os.path.join(self.dir.name, "absent"))

    def test_a_read_that_never_answers_times_out(self):
        release = threading.Event()
        self.addCleanup(release.set)
        with mock.patch.object(host_module, "_read_regular", lambda path, limit: release.wait(10) and b""):
            started = time.monotonic()
            with self.assertRaises(TimeoutError):
                bounded_read("/anything", timeout=0.2)
            self.assertLess(time.monotonic() - started, 2)

    def test_a_config_source_naming_a_fifo_leaves_intent_unknown_without_hanging(self):
        fifo = os.path.join(self.dir.name, "modes.conf")
        os.mkfifo(fifo)
        config = os.path.join(self.dir.name, "hypr", "hyprland.conf")
        os.makedirs(os.path.dirname(config))
        with open(config, "w") as f:
            f.write(DEFAULT + f"source = {fifo}\n")

        class Real(host_module.RealHost):
            def env(self, name):
                return {"HOME": "/nonexistent", "XDG_CONFIG_HOME": os.path.dirname(os.path.dirname(config))}.get(name)

        started = time.monotonic()
        rules = monitor_rules.read(Real())
        self.assertTrue(rules.unavailable)
        self.assertLess(time.monotonic() - started, 2)


class SuccessiveObservationTest(unittest.TestCase):
    """Review finding 5: record mode keeps successive answers in order, so a settled pass replays as a pass."""

    def test_live_settle_pass_records_and_replays_as_a_pass(self):
        class Settling(NativeHost):
            def sleep(self, seconds):
                super().sleep(seconds)
                self.recording["commands"][1] = command(display.MONITORS, json.dumps([monitor()]))

        rec = fixture([monitor(width=2560)], {"USB-1": (3440, 1440)})
        live, saved, _ = record(rec, Settling)
        self.assertEqual(live["status"], "pass")
        self.assertEqual(saved["recording_version"], 2)
        answers = [json.loads(e["stdout"])[0]["width"] for e in saved["commands"] if e["argv"] == display.MONITORS]
        self.assertEqual(answers, [2560, 3440])
        replayed, host = run(saved, RecordedHost)
        self.assertEqual(replayed, live)
        self.assertEqual(host.slept, [2])

    def test_repeats_of_the_last_answer_are_not_saved_and_files_keep_their_sequence(self):
        class Changing(NativeHost):
            reads = 0

            def read_file(self, path):
                if path == "/sys/x":
                    self.reads += 1
                    if self.reads == 2:
                        raise PermissionError(path)
                    return b"one" if self.reads == 1 else b"two"
                return super().read_file(path)

        recorder = RecordingHost(Changing(fixture()))
        recorder.run(ports.DISPLAYS_LIST)
        recorder.run(ports.DISPLAYS_LIST)
        for _ in range(4):
            try:
                recorder.read_file("/sys/x")
            except PermissionError:
                pass
        saved = recorder.recording(Scrubber())
        self.assertEqual(sum(e["argv"] == ports.DISPLAYS_LIST for e in saved["commands"]), 1)
        self.assertEqual(saved["files"]["/sys/x"], [{"text": "one"}, {"error": "permission"}, {"text": "two"}])
        replay = RecordedHost(saved)
        self.assertEqual(replay.read_file("/sys/x"), b"one")
        with self.assertRaises(PermissionError):
            replay.read_file("/sys/x")
        self.assertEqual([replay.read_file("/sys/x") for _ in range(3)], [b"two"] * 3)

    def test_a_recording_without_sequences_stays_version_1(self):
        _, saved, _ = record(fixture())
        self.assertEqual(saved["recording_version"], 1)


class EffectiveMirrorTest(unittest.TestCase):
    """Review finding 6: mirroring comes from the rules that win, not from superseded ones."""

    def lower(self, config):
        return fixture([monitor(width=2560)], {"USB-1": (3440, 1440)}, config)

    def test_an_overridden_mirror_rule_no_longer_hides_a_downgrade(self):
        for config in (DEFAULT + "monitor=USB-1,preferred,auto,1,mirror,eDP-1\nmonitor=USB-1,preferred,auto,1\n",
                       DEFAULT + "monitor=eDP-1,preferred,auto,1,mirror,USB-1\nmonitor=eDP-1,preferred,auto,1\n",
                       "monitor=,preferred,auto,1,mirror,USB-1\nmonitor=,preferred,auto,1\n"):
            with self.subTest(config=config):
                result, _ = run(self.lower(config))
                self.assertEqual(result["status"], "fail")

    def test_an_effective_mirror_rule_still_skips(self):
        for config in (DEFAULT + "monitor=USB-1,preferred,auto,1\nmonitor=USB-1,preferred,auto,1,mirror,eDP-1\n",
                       "monitor=,preferred,auto,1,mirror,eDP-1\n"):
            with self.subTest(config=config):
                result, _ = run(self.lower(config))
                self.assertEqual(result["status"], "skip")
                self.assertIn("mirroring", result["evidence"][1])

    def test_a_connected_source_mirrored_by_description(self):
        rec = fixture([monitor(width=2560, description="Generic Ultrawide"), monitor("USB-2", id=2)],
                      {"USB-1": (3440, 1440), "USB-2": (3440, 1440)},
                      DEFAULT + "monitor=USB-2,preferred,auto,1,mirror,desc:Generic Ultra\n")
        result, _ = run(rec)
        self.assertEqual(result["status"], "skip")
        self.assertTrue(all("mirroring" in line for line in result["evidence"][1:3]))


if __name__ == "__main__":
    unittest.main()
