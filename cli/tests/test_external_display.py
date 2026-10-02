"""External native modes: synthetic EDIDs and a read-only recorded desktop."""

from __future__ import annotations

import base64
import json
import types
import unittest

from omarchy_m_test import external_display as display, monitor_rules, ports
from omarchy_m_test.host import MONITOR_INTENT, Bounded
from omarchy_m_test.privacy import Scrubber
from omarchy_m_test.recording import RecordedHost, RecordingHost
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


class NativeHost(RecordedHost):
    def monitor_intent(self, outputs):
        return monitor_rules.intent(self, outputs)


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
        rec = fixture()
        rec["files"][f"{HOME}/.config/hypr/hyprland.lua"] = {"text": 'require("hypr.monitors")\n'}
        rec["files"][f"{HOME}/.config/hypr/monitors.lua"] = {"text": 'hl.monitor({ output = "USB-1", mode = "2560x1440@60", scale = 1 })\n'}
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
        rec = fixture()
        rec["files"][f"{HOME}/.config/hypr/hyprland.lua"] = {
            "text": 'dofile((os.getenv("OMARCHY_PATH") or "/usr/share/omarchy") .. "/default/hypr/bootstrap.lua")\nrequire("hypr.monitors")\n'}
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
        self.assertEqual(sum("diagnostic: kernel:" in line for line in result["evidence"]), 2)
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


if __name__ == "__main__":
    unittest.main()
