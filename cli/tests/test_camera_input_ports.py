"""Seam A: the camera, the function keys and trackpad, and the USB-C, Thunderbolt/USB4 and external-display checks.

The whole CLI runs one section against the recorded Macs, with scripted
answers: the M2 Max (its ISP, the Thunderbolt lab link to another Mac and the
3440x1440 display on USB-2), the M1 Pro on mx-mac (Hyprland's own list of
its SPI keyboard and trackpad, nothing plugged in) and the M1 Pro on a fresh
converged image (only a charger plugged in: no USB controller, no
Thunderbolt domain). tests/live_mac.py puts
the run at a local seat; the plain recordings are over SSH.
"""

from __future__ import annotations

import copy
import json
import unittest

from omarchy_m_test import camera, inputs, ports
from omarchy_m_test.app import main
from omarchy_m_test.host import LONG_RUNNING, WATCH_TIMEOUT_SECONDS, timeout_for
from omarchy_m_test.recording import EOF, RECORDED_SOURCES, RecordedHost
from tests.desktop import command, recording
from tests.live_mac import LiveMac, live_recording
from tests.test_audio_display import SECTIONS, answer, run
from tests.test_interactive import ARGS, ENTER, check, prompts, report

M1 = "m1-pro-mx-mac"
M1_FRESH = "m1-pro-converged-fresh"
# The fresh M1's USB-C ports with only a charger in: the USB controllers aren't there.
NO_CONTROLLER = ("typec 0 partner=no data=device power=sink\ntypec 1 partner=yes data=device power=sink\n"
                 "typec 2 partner=no data=device power=sink\n")
STICK_IN = NO_CONTROLLER + "usb root speed=480 class=09\nusb root speed=10000 class=09\nusb device speed=5000 class=08\n"
IMAGE_PROMPT = camera.IMAGE_QUESTION + " [y/n/s] "
KEYS_PROMPT = inputs.FUNCTION_KEYS_QUESTION + " [y/n/s] "
GESTURES_PROMPT = inputs.GESTURES_QUESTION + " [y/n/s] "
DEVICES_PROMPT = ports.DEVICES_QUESTION + " [y/n/s] "
PICTURE_PROMPT = ports.PICTURE_QUESTION + " [y/n/s] "
PREVIEW = camera.preview_argv("video0")
FRAMES = camera.frames_argv("video0")
AT_THE_DESKTOP = {"WAYLAND_DISPLAY": "wayland-1"}


def results(host) -> dict[str, dict]:
    return {c["id"]: c for c in report(host)["checks"]}


def questions(host) -> list[str]:
    return [p for p in prompts(host) if p.endswith("[y/n/s] ")]


def section_ids(host, prefix: str) -> list[str]:
    return [c["id"] for c in report(host)["checks"] if c["id"].startswith(prefix)]


def with_command(rec: dict, argv: list[str], returncode: int = 0, stdout: str = "", stderr: str = "") -> dict:
    return answer(rec, argv, returncode, stdout, stderr)


def over_ssh(section: str, answers=(), rec: dict | None = None) -> RecordedHost:
    """The plain recording (the M2's runs are over SSH): no seat, so nothing is shown on its screen."""
    host = RecordedHost(rec or recording(), answers=[ENTER, *answers])
    assert main(["--dry-run"], host, sections=(SECTIONS[section],)) == 0, host.output
    return host


def studio(rec: dict) -> dict:
    """The recorded M2 Max as a Mac Studio (j475c): no built-in camera, keyboard or trackpad."""
    rec = copy.deepcopy(rec)
    rec["files"]["/proc/device-tree/compatible"] = {"text": "apple,j475c\x00apple,t6021\x00apple,arm-platform\x00"}
    rec["files"]["/proc/device-tree/model"] = {"text": "Apple Mac Studio (2023)\x00"}
    return rec


# -- the camera ------------------------------------------------------------------------

class CameraTest(unittest.TestCase):
    def test_the_m2s_isp_gives_frames_and_over_ssh_the_picture_isnt_asked(self):
        host = over_ssh("camera")

        found = results(host)
        self.assertEqual(section_ids(host, "camera."), ["camera.isp", "camera.frames", "camera.image"])
        self.assertEqual((found["camera.isp"]["status"], found["camera.isp"]["classification"]["outcome"]), ("pass", "works"))
        self.assertEqual((found["camera.isp"]["classification"]["feature"], found["camera.isp"]["classification"]["layer"]),
                         ("isp-camera", "aurora"))
        self.assertEqual(found["camera.isp"]["evidence"], ["camera: /dev/video0, from the ISP driver (apple-isp)"])
        self.assertEqual(found["camera.frames"]["status"], "pass")
        self.assertEqual(found["camera.frames"]["evidence"], [
            "asked ffmpeg for 30 frames from /dev/video0 (read and discarded, none kept)",
            "stream: 1920x1080, nv12",
            "frames: 30 of 30",
        ])
        self.assertEqual((found["camera.image"]["kind"], found["camera.image"]["status"]), ("human", "skip"))
        self.assertEqual(found["camera.image"]["evidence"], ["skipped: no Wayland desktop session to show the camera in"])
        self.assertNotIn(PREVIEW, host.commands_run)
        self.assertNotIn(IMAGE_PROMPT, prompts(host))

    def test_at_the_desktop_the_camera_is_shown_live_and_the_human_confirms_the_image(self):
        rec = with_command(live_recording(env=AT_THE_DESKTOP), PREVIEW, returncode=camera.TIMED_OUT)
        host = run("camera", ["y looks fine"], rec=rec)

        result = check(host, "camera.image")
        self.assertEqual((result["kind"], result["status"], result["classification"]["outcome"]), ("human", "pass", "works"))
        self.assertEqual(result["evidence"][0], "showed /dev/video0 live for 10 s (mpv)")
        self.assertEqual(result["evidence"][-1], "note: looks fine")
        self.assertLess(host.commands_run.index(FRAMES), host.commands_run.index(PREVIEW))
        self.assertLess(host.output.index("A window shows the camera"), host.output.index(IMAGE_PROMPT))

    def test_a_bad_picture_is_the_humans_failure(self):
        rec = with_command(live_recording(env=AT_THE_DESKTOP), PREVIEW, returncode=camera.TIMED_OUT)
        result = check(run("camera", ["n upside down"], rec=rec), "camera.image")

        self.assertEqual((result["status"], result["classification"]["outcome"]), ("fail", "fails"))

    def test_without_the_isp_device_the_camera_fails_and_a_usb_webcam_is_named_by_driver_only(self):
        rec = with_command(recording(), camera.DEVICES, stdout="video2 uvcvideo\nvideo3 uvcvideo\n")
        host = over_ssh("camera", rec=rec)

        found = results(host)
        self.assertEqual((found["camera.isp"]["status"], found["camera.isp"]["classification"]["outcome"]), ("fail", "fails"))
        self.assertEqual(found["camera.isp"]["evidence"], [
            "no camera device from the ISP driver (apple-isp)",
            "other video devices: video2 (uvcvideo), video3 (uvcvideo)",
        ])
        self.assertEqual(found["camera.frames"]["evidence"], ["skipped: no camera device (see camera.isp)"])
        self.assertEqual(found["camera.image"]["status"], "skip")
        self.assertFalse(any(argv[:3] == ["timeout", "20", "ffmpeg"] for argv in host.commands_run))

    def test_a_camera_that_gives_no_frames_fails_and_isnt_shown(self):
        stderr = "[video4linux2,v4l2 @ 0x1] ioctl(VIDIOC_STREAMON): Input/output error\n/dev/video0: Input/output error\n"
        rec = with_command(live_recording(env=AT_THE_DESKTOP), FRAMES, returncode=1, stderr=stderr)
        host = run("camera", [], rec=rec)

        frames = check(host, "camera.frames")
        self.assertEqual((frames["status"], frames["classification"]["outcome"]), ("fail", "fails"))
        self.assertEqual(frames["evidence"][-2:], ["frames: 0 of 30", "ffmpeg: /dev/video0: Input/output error"])
        self.assertEqual(check(host, "camera.image")["evidence"], ["skipped: the camera gave no frames (see camera.frames)"])
        self.assertNotIn(PREVIEW, host.commands_run)

    def test_without_ffmpeg_or_mpv_the_checks_that_need_them_are_skipped(self):
        no_ffmpeg = with_command(recording(), FRAMES, returncode=127, stderr="timeout: failed to run command 'ffmpeg'\n")
        self.assertEqual(results(over_ssh("camera", rec=no_ffmpeg))["camera.frames"]["evidence"], ["skipped: ffmpeg isn't installed"])

        no_mpv = with_command(live_recording(env=AT_THE_DESKTOP), PREVIEW, returncode=127)
        host = run("camera", [], rec=no_mpv)
        self.assertEqual(check(host, "camera.image")["evidence"], ["skipped: mpv isn't installed"])
        self.assertNotIn(IMAGE_PROMPT, prompts(host))

    def test_a_mac_without_a_built_in_camera_skips_without_opening_anything(self):
        host = over_ssh("camera", rec=studio(recording()))

        found = results(host)
        self.assertEqual({k: v["status"] for k, v in found.items() if k.startswith("camera.")},
                         {"camera.isp": "skip", "camera.frames": "skip", "camera.image": "skip"})
        self.assertEqual(found["camera.isp"]["evidence"], ["skipped: this Mac has no built-in camera"])
        self.assertNotIn(camera.DEVICES, host.commands_run)


# -- the function keys and the trackpad ----------------------------------------------------

class KeysAndTrackpadTest(unittest.TestCase):
    def run_input(self, answers, rec=None) -> LiveMac:
        # The M1 on mx-mac has no light sensor: the keyboard-light question isn't asked first.
        return run("input", answers, rec=rec or live_recording(base=recording(M1)))

    def test_the_m1s_spi_keyboard_and_trackpad_are_named_and_the_human_answers(self):
        host = self.run_input(["y", "n two-finger scroll jumps"])

        keys, gestures = check(host, "input.function-keys"), check(host, "input.trackpad-gestures")
        self.assertEqual((keys["kind"], keys["status"], keys["classification"]["feature"]), ("human", "pass", "keyboard"))
        self.assertEqual(keys["evidence"][0], "built-in keyboard (Hyprland): apple-spi-keyboard")
        self.assertEqual((gestures["status"], gestures["classification"]["feature"], gestures["classification"]["outcome"]),
                         ("fail", "touchpad", "fails"))
        self.assertEqual(gestures["evidence"][0], "built-in trackpad (Hyprland): apple-spi-trackpad")
        self.assertEqual(gestures["evidence"][-1], "note: two-finger scroll jumps")
        self.assertEqual(prompts(host)[-2:], [KEYS_PROMPT, GESTURES_PROMPT])
        self.assertEqual(host.commands_run.count(inputs.DEVICES), 1)  # read once for both

    def test_the_m2s_mtp_keyboard_and_what_the_top_row_sends(self):
        rec = with_command(live_recording(), inputs.DEVICES, stdout="apple-mtp-keyboard\napple-mtp-multi-touch\n")
        rec["files"][inputs.FNMODE] = {"text": "2\n"}
        host = run("input", [EOF, "s", "s"], rec=rec)

        self.assertEqual(check(host, "input.function-keys")["evidence"][:2], [
            "built-in keyboard (Hyprland): apple-mtp-keyboard",
            "hid_apple fnmode: 2 (F-keys first, media keys with Fn)",
        ])
        self.assertEqual(check(host, "input.trackpad-gestures")["evidence"][0], "built-in trackpad (Hyprland): apple-mtp-multi-touch")

    def test_keyboards_and_mice_people_plug_in_or_pair_never_leave_the_mac(self):
        # The script on the Mac keeps only the built-in drivers' names from Hyprland's list, so a
        # paired "kestrel's-magic-keyboard" never reaches a recording; the CLI filters again.
        self.assertIn("apple-(spi|mtp|internal)-", inputs.BUILT_IN_SCRIPT)
        self.assertNotIn("hyprctl devices -j", [" ".join(argv) for argv in RECORDED_SOURCES])
        rec = with_command(live_recording(base=recording(M1)), inputs.DEVICES,
                           stdout="apple-spi-keyboard\nkestrel's-magic-keyboard\napple-spi-trackpad\n")
        host = self.run_input(["s", "s"], rec=rec)

        self.assertNotIn("magic-keyboard", json.dumps(report(host)))
        self.assertNotIn(["hyprctl", "devices", "-j"], host.commands_run)

    def test_over_ssh_hyprland_cant_list_the_devices_and_the_questions_are_still_asked(self):
        host = over_ssh("input", [EOF, "s", "s"])

        self.assertEqual(results(host)["input.function-keys"]["evidence"][0],
                         "Hyprland couldn't list the input devices (run from the desktop to see them)")
        self.assertEqual(prompts(host)[-2:], [KEYS_PROMPT, GESTURES_PROMPT])

    def test_a_mac_without_a_built_in_keyboard_or_trackpad_doesnt_ask(self):
        host = over_ssh("input", [EOF], rec=studio(recording()))

        found = results(host)
        self.assertEqual(found["input.function-keys"]["evidence"], ["skipped: this Mac has no built-in keyboard"])
        self.assertEqual(found["input.trackpad-gestures"]["evidence"], ["skipped: this Mac has no built-in trackpad"])
        self.assertNotIn(KEYS_PROMPT, prompts(host))


# -- USB-C, Thunderbolt/USB4 and external displays ---------------------------------------------

class PortsTest(unittest.TestCase):
    def test_at_the_mac_the_human_plugs_in_first_then_the_m2s_ports_link_and_display_are_listed(self):
        host = run("ports", [ENTER, "y", "y"])

        messages = [event[1] for event in host.transcript if event[0] == "prompt"]
        self.assertEqual(messages[1:], [ports.READY, DEVICES_PROMPT, PICTURE_PROMPT])
        first_script = min(host.commands_run.index(argv) for argv in (ports.USB, ports.THUNDERBOLT_LIST, ports.DISPLAYS_LIST))
        self.assertGreater(first_script, 0)
        self.assertLess(host.output.index(ports.PLUG_IN), host.output.index("Found:"))
        self.assertEqual(section_ids(host, "ports."), list(ports.CHECK_IDS))

        found = results(host)
        self.assertEqual({k: (v["status"], v["classification"]["feature"], v["classification"]["outcome"])
                          for k, v in found.items() if k.startswith("ports.")}, {
            "ports.usb-c": ("pass", "usb3-tb-ports", "works"),
            "ports.thunderbolt": ("pass", "thunderbolt", "works"),
            "ports.external-displays": ("pass", "usb4-displays", "works"),
            "ports.devices-work": ("pass", "usb3-tb-ports", "works"),
            "ports.external-display-picture": ("pass", "usb4-displays", "works"),
        })
        self.assertEqual(found["ports.usb-c"]["evidence"], [
            "USB-C ports: 3 (USB-PD controller, /sys/class/typec), 2 with something plugged in",
            "port 0: plugged in (data host, power source)",
            "port 1: plugged in (data host, power source)",
            "USB controllers: 6 root hubs (480 Mbps, 10000 Mbps)",
            "USB devices: none",
        ])
        self.assertEqual(found["ports.thunderbolt"]["evidence"], [
            "Thunderbolt/USB4 controllers: 3 (domains registered by thunderbolt-apple-nhi)",
            "linked: another computer, host-to-host (10.0 Gb/s, 2 lanes)",
            "retimers: 1",
        ])
        self.assertEqual(found["ports.external-displays"]["evidence"], [
            "USB-C display connectors: 3 (USB-1, USB-2, USB-3)",
            "USB-2: in use, 3440x1440 preferred",
        ])
        self.assertEqual(found["ports.external-display-picture"]["evidence"][0], "display on USB-C: USB-2 at 3440x1440")

    def test_over_ssh_nobody_is_asked_to_plug_anything_in(self):
        host = over_ssh("ports", [EOF, EOF])

        self.assertNotIn(ports.READY, [event[1] for event in host.transcript if event[0] == "prompt"])
        self.assertEqual(prompts(host)[-2:], [DEVICES_PROMPT, PICTURE_PROMPT])

    def test_usb_devices_are_listed_by_class_and_speed(self):
        usb = ("typec 0 partner=yes data=host power=source\ntypec 1 partner=no data=device power=sink\n"
               "usb root speed=480 class=09\nusb root speed=10000 class=09\n"
               "usb device speed=5000 class=08\nusb device speed=480 class=09\nusb device speed=12 class=03\n")
        host = over_ssh("ports", [EOF], rec=with_command(recording(M1), ports.USB, stdout=usb))

        found = results(host)
        self.assertEqual(found["ports.usb-c"]["evidence"][-1],
                         "USB devices: 3: storage at 5000 Mbps, hub at 480 Mbps, input (HID) at 12 Mbps")
        self.assertEqual(found["ports.devices-work"]["evidence"][0], "listed: 1 USB-C port(s) in use, 3 USB device(s), 0 Thunderbolt/USB4 link(s)")
        # No display on USB-C: its picture isn't asked about.
        self.assertEqual(found["ports.external-display-picture"]["evidence"], ["skipped: no display in use on a USB-C port"])

    def test_a_thunderbolt_device_shows_its_generation_speed_lanes_and_whether_it_is_authorized(self):
        tb = ("thunderbolt 0-0 thunderbolt_device generation=4 rx_speed=20.0Gb/s rx_lanes=2 authorized=1\n"
              "thunderbolt 0-1 thunderbolt_device generation=3 rx_speed=20.0Gb/s rx_lanes=2 authorized=0\n"
              "thunderbolt domain0 thunderbolt_domain\n")
        host = over_ssh("ports", [EOF], rec=with_command(recording(M1), ports.THUNDERBOLT_LIST, stdout=tb))

        self.assertEqual(results(host)["ports.thunderbolt"]["evidence"], [
            "Thunderbolt/USB4 controllers: 1 (domains registered by thunderbolt-apple-nhi)",
            "linked: a Thunderbolt or USB4 device (generation 3, 20.0 Gb/s, 2 lanes, not authorized)",
        ])

    def test_nothing_plugged_in_asks_nothing(self):
        host = over_ssh("ports", [], rec=recording(M1))

        found = results(host)
        self.assertEqual(found["ports.devices-work"]["evidence"], ["skipped: nothing plugged into the USB-C ports"])
        self.assertEqual(found["ports.external-displays"]["status"], "skip")
        self.assertEqual(found["ports.external-displays"]["evidence"][-1], "skipped: no display plugged into a USB-C port")
        self.assertEqual(questions(host), [])

    def test_without_the_thunderbolt_driver_the_aurora_feature_fails(self):
        for stdout, why in (("nobus\n", "no Thunderbolt bus in this kernel"), ("", "no domain registered")):
            with self.subTest(why=why):
                host = over_ssh("ports", [EOF, EOF], rec=with_command(recording(), ports.THUNDERBOLT_LIST, stdout=stdout))

                result = results(host)["ports.thunderbolt"]
                self.assertEqual((result["status"], result["classification"]["outcome"]), ("fail", "fails"))
                self.assertEqual(result["classification"]["expected"]["aurora"], "supported")
                self.assertIn(why, result["evidence"][0])

    def test_a_display_connected_but_not_lit_fails_and_its_picture_isnt_asked(self):
        drm = "connector card1-eDP-1 connected enabled 3456x2234\nconnector card2-USB-2 connected disabled 3440x1440\n"
        host = over_ssh("ports", [EOF], rec=with_command(recording(), ports.DISPLAYS_LIST, stdout=drm))

        found = results(host)
        self.assertEqual((found["ports.external-displays"]["status"], found["ports.external-displays"]["classification"]["outcome"]),
                         ("fail", "fails"))
        self.assertIn("USB-2: connected but not in use, 3440x1440 preferred", found["ports.external-displays"]["evidence"])
        self.assertEqual(found["ports.external-display-picture"]["status"], "skip")
        self.assertNotIn(PICTURE_PROMPT, prompts(host))

    def test_a_kernel_without_usb_c_display_connectors_fails_and_hdmi_is_only_noted(self):
        drm = "connector card0-eDP-1 connected enabled 3456x2234\nconnector card0-HDMI-A-1 connected enabled 1920x1080\n"
        host = over_ssh("ports", [EOF], rec=with_command(recording(), ports.DISPLAYS_LIST, stdout=drm))

        result = results(host)["ports.external-displays"]
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["evidence"], [
            "no display connectors on the USB-C ports (no DP alt mode in this kernel)",
            "HDMI-A-1: connected (HDMI, not USB-C: see display.outputs)",
        ])

    def test_without_the_usb_pd_controller_usb_c_fails(self):
        usb = "usb root speed=480 class=09\n"
        result = results(over_ssh("ports", [EOF, EOF], rec=with_command(recording(), ports.USB, stdout=usb)))["ports.usb-c"]

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["evidence"][0], "no USB-C ports registered (the USB-PD controller, tipd, didn't come up)")

    def test_the_fresh_m1_over_ssh_with_nothing_attached_skips_usb_and_thunderbolt_is_an_expected_gap(self):
        rec = recording(M1_FRESH)
        del rec["env"]["HOME"]  # no checkpoint: this run is only the one section
        host = over_ssh("ports", [EOF], rec=rec)

        found = results(host)
        usb = found["ports.usb-c"]
        self.assertEqual((usb["status"], usb["classification"]["outcome"]), ("skip", "not-tested"))
        self.assertEqual(usb["evidence"], [
            "USB-C ports: 4 (USB-PD controller, /sys/class/typec), 1 with something plugged in",
            "port 1: plugged in (data device, power sink)",
            "no USB controller (no root hub in /sys/bus/usb)",
            "USB devices: none",
            "skipped: no USB device attached (the USB controller only comes up while something is plugged into a USB-C port)",
        ])
        self.assertNotIn(ports.USB_WAIT, host.commands_run)
        self.assertNotIn(ports.PLUG_USB_READY, [event[1] for event in host.transcript if event[0] == "prompt"])
        # No domain on the M1: Aurora doesn't bring Thunderbolt up there yet, so it's a gap, not "should work".
        links = found["ports.thunderbolt"]
        self.assertEqual((links["status"], links["classification"]["outcome"]), ("fail", "not-in-asahi"))
        self.assertEqual(links["classification"]["expected"], {"asahi": "wip", "aurora": "unsupported"})

    def test_at_the_mac_with_no_usb_controller_the_human_plugs_a_device_in_and_the_controller_comes_up(self):
        rec = with_command(with_command(live_recording(), ports.USB, stdout=NO_CONTROLLER), ports.USB_WAIT, stdout=STICK_IN)
        host = run("ports", [ENTER, ENTER, "y", "y"], rec=rec)

        messages = [event[1] for event in host.transcript if event[0] == "prompt"]
        self.assertEqual(messages[1:3], [ports.READY, ports.PLUG_USB_READY])
        self.assertLess(host.output.index(ports.PLUG_USB), host.output.index("Found:"))
        self.assertLess(host.commands_run.index(ports.USB), host.commands_run.index(ports.USB_WAIT))
        usb = results(host)["ports.usb-c"]
        self.assertEqual((usb["status"], usb["classification"]["outcome"]), ("pass", "works"))
        self.assertEqual(usb["evidence"][-3:], [
            "USB controllers: 2 root hubs (480 Mbps, 10000 Mbps)",
            "USB devices: 1: storage at 5000 Mbps",
            "the USB controller came up once a USB device was plugged in",
        ])

    def test_at_the_mac_a_controller_that_never_comes_up_after_plugging_in_fails(self):
        rec = with_command(with_command(live_recording(), ports.USB, stdout=NO_CONTROLLER), ports.USB_WAIT, stdout=NO_CONTROLLER)
        usb = results(run("ports", [ENTER, ENTER, "y", "y"], rec=rec))["ports.usb-c"]

        self.assertEqual((usb["status"], usb["classification"]["outcome"]), ("fail", "fails"))
        self.assertEqual(usb["evidence"][-1], f"no USB controller came up within {ports.USB_WAIT_SECONDS} s of plugging in a USB device")

    def test_at_the_mac_the_human_can_skip_plugging_a_usb_device_in(self):
        for skip in ("s", EOF):
            with self.subTest(skip=skip):
                rec = with_command(live_recording(), ports.USB, stdout=NO_CONTROLLER)
                host = run("ports", [ENTER, skip, "y", "y"], rec=rec)

                usb = results(host)["ports.usb-c"]
                self.assertEqual(usb["status"], "skip")
                self.assertTrue(usb["evidence"][-1].endswith("plugging one in was skipped"), usb["evidence"][-1])
                self.assertNotIn(ports.USB_WAIT, host.commands_run)

    def test_the_wait_for_the_usb_controller_is_a_watch_with_the_long_timeout(self):
        self.assertTrue(ports.USB_WAIT_SCRIPT.startswith(LONG_RUNNING))
        self.assertEqual(timeout_for(ports.USB_WAIT), WATCH_TIMEOUT_SECONDS)

    def test_the_scripts_never_read_a_name_vendor_string_or_serial(self):
        for script in (ports.USB_SCRIPT, ports.USB_WAIT_SCRIPT, ports.THUNDERBOLT_SCRIPT, ports.DISPLAYS_SCRIPT, camera.DEVICES_SCRIPT):
            for private in ("product", "manufacturer", "serial", "device_name", "vendor_name", "unique_id", "/name", "edid"):
                self.assertNotIn(private, script)


if __name__ == "__main__":
    unittest.main()
