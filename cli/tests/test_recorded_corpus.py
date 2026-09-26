"""Seam A: record mode, the recorded-Mac corpus and privacy.

The whole CLI runs in record mode against the real M1 and M2 evidence in
tests/corpus/ (kernel logs, device-tree dump, first-boot, Wi-Fi and lid
journals, uname, PCI devices and addresses), exactly as it would on
the Mac. The tests assert on what comes out: the recording it saved, the
report it wrote, and that replaying the recording gives the same run.
"""

from __future__ import annotations

import json
import os
import re
import unittest

from omarchy_m_test import privacy
from omarchy_m_test.app import main
from omarchy_m_test.recording import ENDED, RECORDED_SOURCES, RecordedHost, RecordingHost
from tests.corpus import MACHINES, forbidden, raw_host, raw_recording, seeded_recording_path
from tests.schema_validator import errors

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_DIR = os.path.join(os.path.dirname(os.path.dirname(HERE)), "schema")
REPORT_FILE = "omarchy-m-test-report.json"
RECORDING_FILE = "m.json"
ENTER = ""


def read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


SCHEMA = json.loads(read(os.path.join(SCHEMA_DIR, "report-v1.schema.json")))

# Identifier shapes that must not survive anywhere in a saved recording or a
# report, whatever machine they came from.
LEAK_PATTERNS = {
    "MAC address": re.compile(r"(?<![0-9A-Fa-f:])[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}(?![0-9A-Fa-f])"),
    "IPv4 address": re.compile(r"(?<![\w.])(\d{1,3}\.){3}\d{1,3}(?![\w]|\.\d)"),
    "IPv6 address": re.compile(r"(?i)(?<![\w:])fe80::[0-9a-f:]+"),
    "UUID": re.compile(r"(?i)[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"),
    "long hex identifier": re.compile(r"(?<![0-9A-Za-z])(0x)?[0-9A-Fa-f]{16,}(?![0-9A-Za-z])"),
    "home path": re.compile(r"/home/[^\s<]"),
    "underscored Bluetooth address": re.compile(r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{2}(_[0-9A-Fa-f]{2}){5}(?![0-9A-Fa-f])"),
}

# Device identifiers in the formats the tools print them (displays, audio cards,
# USB and Thunderbolt devices, Bluetooth), each with the identifiers it carries.
DEVICE_SERIALS = {
    ("hyprctl", "monitors", "-j"): (
        '[{"id": 0, "name": "eDP-1", "description": "Apple Computer Inc 0x0000", "make": "Apple Computer Inc", "model": "", "serial": ""},\n'
        ' {"id": 1, "name": "USB-2", "description": "Dell Inc. DELL U3423WE 9RKXZN3 (DP-2)", "make": "Dell Inc.",\n'
        '  "model": "DELL U3423WE", "serial": "9RKXZN3", "width": 3440}]\n',
        ("9RKXZN3",),
    ),
    ("hyprctl", "monitors"): ("Monitor USB-2 (ID 1):\n\t3440x1440@59.97300 at 1728x0\n\tdescription: Dell Inc. DELL U3423WE 9RKXZN3 (DP-2)\n"
                             "\tmake: Dell Inc.\n\tmodel: DELL U3423WE\n\tserial: 9RKXZN3\n", ("9RKXZN3",)),
    ("edid-decode", "/sys/class/drm/card1-DP-2/edid"): (
        "Block 0, Base EDID:\n  Vendor & Product Identification:\n    Manufacturer: DEL\n    Model: 41586\n"
        "    Serial Number: 1112231500 (0x424b4c4c)\n  Display Descriptors:\n    Display Product Serial Number: '9RK XZN3'\n",
        ("1112231500", "424b4c4c", "9RK XZN3"),
    ),
    ("pactl", "list", "cards"): ('Card #52\n\tName: alsa_card.usb-Generic_USB_Audio_201405280001-00\n\tProperties:\n'
                                 '\t\tdevice.serial = "Generic_USB_Audio_201405280001"\n\t\tdevice.vendor.name = "Generic"\n',
                                 ("201405280001",)),
    ("wpctl", "inspect", "52"): ('id 52, type PipeWire:Interface:Device\n  * device.name = "alsa_card.usb-Generic_USB_Audio_201405280001-00"\n'
                                 '    device.serial = "Generic_USB_Audio_201405280001"\n', ("201405280001",)),
    ("udevadm", "info", "/dev/snd/controlC1"): ("E: ID_SERIAL=Generic_USB_Audio_201405280001\nE: ID_SERIAL_SHORT=201405280001\n"
                                                "E: ID_USB_SERIAL=Generic_USB_Audio_201405280001\nE: ID_USB_SERIAL_SHORT=201405280001\n",
                                                ("201405280001",)),
    ("lsusb", "-v", "-s", "1:2"): ("  iSerial                 3 201405280001\n", ("201405280001",)),
    ("boltctl", "list"): (" ● OWC Thunderbolt 3 Dock\n   ├─ uuid:          d6010000-0082-8718-a3c4-8c2b4e3f5a91\n"
                          '   └─ "unique_id": "0082871a3c48c2b4"\n', ("d6010000-0082-8718-a3c4-8c2b4e3f5a91", "0082871a3c48c2b4")),
    ("bluetoothctl", "devices"): ("Device 7C:C1:80:12:34:56 AirPods Pro\nController F0:C0:7B:98:E6:D4 omarchy [default]\n",
                                  ("7C:C1:80:12:34:56", "F0:C0:7B:98:E6:D4")),
    ("pw-dump",): ('    "node.name": "bluez_output.7C_C1_80_12_34_56.1",\n    "api.bluez5.path": "/org/bluez/hci0/dev_7C_C1_80_12_34_56",\n',
                   ("7C_C1_80_12_34_56",)),
}
# Names people give their devices, in the formats the tools print them, each with what
# must not come out and what must stay readable; a display mode that isn't an e-mail
# address; and edid-decode's raw hex dump (the serial as bytes).
DEVICE_NAMES = {
    ("bluetoothctl", "devices"): ("Device 7C:C1:80:12:34:56 Marcelo's AirPods Pro\nController F0:C0:7B:98:E6:D4 Kestrel's MacBook Pro [default]\n"
                                  "Device 11:22:33:44:55:66 Magic Keyboard\n[CHG] Device 7C:C1:80:12:34:56 RSSI: -60\n",
                                  ("Marcelo", "Kestrel"), ("Device <mac> <device-name>", "Controller <mac> <device-name> [default]",
                                                           "Device <mac> Magic Keyboard", "Device <mac> RSSI: -60")),
    ("bluetoothctl", "info", "7C:C1:80:12:34:56"): (
        "Device 7C:C1:80:12:34:56 (public)\n\tName: Marcelo's AirPods Pro\n\tAlias: Kestrel Pods\n\tClass: 0x00240418\n\tPaired: yes\n"
        "[CHG] Device 7C:C1:80:12:34:56 Alias: Pods of Kestrel\n",
        ("Marcelo", "Kestrel"), ("Device <mac> (public)", "\tAlias: <device-name>", "\tClass: 0x00240418", "Alias: <device-name>"),
    ),
    ("pw-dump",): (
        '[\n  {\n    "id": 60,\n    "info": {\n      "props": {\n        "device.api": "bluez5",\n        "api.bluez5.address": "7C:C1:80:12:34:56",\n'
        '        "device.alias": "O\'Neill\'s Pods",\n        "device.description": "Marcelo\'s AirPods Pro"\n      }\n    }\n  },\n'
        '  {\n    "id": 61,\n    "info": {\n      "props": {\n        "node.name": "alsa_output.platform-sound.HiFi__Speaker__sink",\n'
        '        "node.description": "MacBook Pro Speakers"\n      }\n    }\n  }\n]\n',
        ("Marcelo", "O'Neill"), ('"node.description": "MacBook Pro Speakers"', '"device.description": "<device-name>"', '"device.alias": "<device-name>"'),
    ),
    ("pactl", "list", "sinks"): (
        "Sink #60\n\tName: bluez_output.7C_C1_80_12_34_56.1\n\tDescription: Marcelo's AirPods Pro\n"
        "Sink #61\n\tName: alsa_output.platform-sound.HiFi__Speaker__sink\n\tDescription: MacBook Pro Speakers\n",
        ("Marcelo",), ("\tDescription: <device-name>", "\tDescription: MacBook Pro Speakers"),
    ),
    ("wpctl", "status"): (" ├─ Sinks:\n │  *   60. Marcelo's AirPods Pro             [vol: 0.40]\n │      61. MacBook Pro Speakers [vol: 0.45]\n",
                          ("Marcelo",), ("60. <device-name>", "61. MacBook Pro Speakers")),
    ("hostnamectl",): ("   Static hostname: kestrels-mac\n   Pretty hostname: Kestrel's MacBook Pro\n  Hardware Vendor: Apple Inc.\n",
                       ("Kestrel", "kestrels-mac"), ("Pretty hostname: <device-name>", "Hardware Vendor: Apple Inc.")),
    ("hyprctl", "monitors", "all"): ("Monitor USB-2 (ID 1):\n\t3440x1440@59.97300 at 1728x0\n", (), ("\t3440x1440@59.97300 at 1728x0",)),
    ("edid-decode", "/sys/class/drm/card1-DP-2/edid", "--raw"): (
        "edid-decode (hex):\n\n00 ff ff ff ff ff ff 00 10 ac 42 a2 4c 4c 4b 42\n1c 21 01 04 b5 50 21 78 3b 8f 05 ad 50 45 a8 25\n"
        "00 00 00 ff 00 39 52 4b 58 5a 4e 33 0a 20 20 20\n\n----------------\n\nBlock 0, Base EDID:\n",
        ("4c 4c 4b 42", "39 52 4b 58"), ("edid-decode (hex):\n\n[hex dump removed]\n\n----------------", "Block 0, Base EDID:"),
    ),
}
# Read as a file: /etc/machine-info holds the pretty hostname too.
MACHINE_INFO = ("/etc/machine-info", 'PRETTY_HOSTNAME="Kestrel\'s MacBook Pro"\nCHASSIS=laptop\n')
# sysfs files that hold nothing but a serial.
SERIAL_FILES = {
    "/sys/bus/usb/devices/1-2/serial": "201405280001\n",
    "/sys/bus/thunderbolt/devices/0-1/unique_id": "d6010000-0082-8718-a3c4-8c2b4e3f5a91\n",
    "/sys/class/drm/card1-DP-2/device/serial_number": "Z9RKX\n",
}

# What each machine's raw evidence is known to contain (the M1 evidence has
# no MAC address, home path, UUID or long hex id).
CORPUS_HOLDS = {
    "m2-max-image2": ("MAC address", "IPv4 address", "IPv6 address", "UUID", "long hex identifier", "home path"),
    "m1-pro-mx-mac": ("IPv4 address", "IPv6 address"),
    "m1-pro-converged": ("MAC address", "IPv4 address", "UUID", "long hex identifier", "home path"),
}


def record(machine: str) -> RecordedHost:
    """Run the whole CLI in record mode on a corpus machine."""
    mac = raw_host(machine, answers=[ENTER, ENDED])
    status = main(["--dry-run", "--record", RECORDING_FILE], mac)
    assert status == 0, mac.output
    return mac


class RecordModeTest(unittest.TestCase):
    def test_record_mode_saves_the_run_and_the_recorded_sources(self):
        for machine in MACHINES:
            with self.subTest(machine=machine):
                mac = record(machine)

                recording = json.loads(mac.written[RECORDING_FILE])
                self.assertEqual(recording["recording_version"], 1)
                recorded = [entry["argv"] for entry in recording["commands"]]
                self.assertIn(["uname", "-r"], recorded)
                available = [entry["argv"] for entry in raw_recording(machine)["commands"]]
                for source in RECORDED_SOURCES:
                    self.assertEqual(source in recorded, source in available, source)
                self.assertIn("/proc/device-tree/model", recording["files"])
                self.assertIn(f"Recording saved to {RECORDING_FILE}", mac.output)
                self.assertIn(REPORT_FILE, mac.written)
                self.assertEqual(mac.posts, [])

    def test_declining_the_disclaimer_records_nothing(self):
        mac = raw_host("m2-max-image2", answers=["n"])

        status = main(["--record", RECORDING_FILE], mac)

        self.assertEqual(status, 1)
        self.assertEqual(mac.written, {})
        self.assertNotIn(["journalctl", "--dmesg", "--boot=0", "--no-pager"], mac.commands_run)

    def test_a_refused_machine_records_only_what_identifying_it_read(self):
        pc = RecordedHost.load(os.path.join(HERE, "recordings", "x86-laptop.json"))

        status = main(["--record", RECORDING_FILE], pc)

        self.assertEqual(status, 2)
        recording = json.loads(pc.written[RECORDING_FILE])
        self.assertEqual(recording["files"], {"/proc/device-tree/compatible": None})
        self.assertEqual(recording["commands"], [])
        replay = RecordedHost(recording)
        self.assertEqual(main([], replay), 2)
        self.assertIn("only runs on Apple Silicon Macs", replay.output)

    def test_a_recording_replays_the_same_run(self):
        for machine in MACHINES:
            with self.subTest(machine=machine):
                recorded = record(machine)

                saved = json.loads(recorded.written[RECORDING_FILE])
                if "HOME" in saved.get("env", {}):
                    # Record mode never checkpoints; a replay does, and finds no earlier run's checkpoint.
                    saved["files"][f"{saved['env']['HOME']}/.local/state/omarchy-m-test/checkpoint.json"] = None
                replay = RecordedHost(saved, answers=[ENTER, ENDED])
                status = main(["--dry-run"], replay)

                self.assertEqual(status, 0)
                self.assertEqual(replay.written[REPORT_FILE], recorded.written[REPORT_FILE])
                self.assertEqual(replay.written[REPORT_FILE], read(os.path.join(SCHEMA_DIR, "golden", f"{machine}.json")))
                self.assertEqual(errors(SCHEMA, json.loads(replay.written[REPORT_FILE])), [])

    def test_the_seeded_recordings_are_what_record_mode_saves_from_the_evidence(self):
        for machine in MACHINES:
            with self.subTest(machine=machine):
                saved = json.loads(record(machine).written[RECORDING_FILE])
                seeded = json.loads(read(seeded_recording_path(machine)))

                for part in ("recording_version", "commands", "files", "dirs"):
                    self.assertEqual(seeded[part], saved[part], f"{part}: run scripts/reseed_recordings.py")

    def test_recordings_keep_the_evidence_later_checks_need(self):
        m2 = json.loads(read(seeded_recording_path("m2-max-image2")))
        outputs = {tuple(entry["argv"]): entry["stdout"] for entry in m2["commands"]}

        kernel = outputs[("journalctl", "--dmesg", "--boot=0", "--no-pager")]
        self.assertIn("kernel: Machine model: Apple MacBook Pro (16-inch, M2 Max, 2023)", kernel)
        self.assertIn("brcmfmac", kernel)
        first_boot = outputs[("journalctl", "--unit=omarchy-provision-hardware.service", "--output=short-iso", "--no-pager")]
        self.assertIn("Deferred hardware step failed: install/hardware/vulkan.sh", first_boot)
        wifi = outputs[("journalctl", "--boot=0", "--unit=NetworkManager.service", "--unit=iwd.service", "--output=short-precise", "--no-pager")]
        self.assertIn("Activation: starting connection '<ssid>'", wifi)
        self.assertIn("bss: <mac>", wifi)
        self.assertIn("address=<ip>", wifi)
        self.assertIn("Lid closed.", outputs[("journalctl", "--boot=0", "--unit=systemd-logind.service", "--no-pager")])
        dts = outputs[("dtc", "-I", "fs", "-O", "dts", "/proc/device-tree")]
        self.assertIn('compatible = "apple,j416c", "apple,t6021", "apple,arm-platform";', dts)
        self.assertIn("local-mac-address = <redacted>;", dts)


class ZeroLeakTest(unittest.TestCase):
    """Real M1/M2 kernel logs and device-tree dumps go in; no identifier comes out."""

    def test_the_corpus_really_contains_the_identifiers(self):
        for machine in MACHINES:
            with self.subTest(machine=machine):
                raw = json.dumps(raw_recording(machine), ensure_ascii=False)
                for value in forbidden(machine):
                    self.assertIn(value, raw)
                for kind in CORPUS_HOLDS[machine]:
                    self.assertRegex(raw, LEAK_PATTERNS[kind], kind)

    def test_no_forbidden_identifier_reaches_a_recording_or_a_report(self):
        for machine in MACHINES:
            mac = record(machine)
            for output in (RECORDING_FILE, REPORT_FILE):
                text = mac.written[output]
                with self.subTest(machine=machine, output=output):
                    for value in forbidden(machine):
                        self.assertNotIn(value.lower(), text.lower())
                    for kind, pattern in LEAK_PATTERNS.items():
                        match = pattern.search(text)
                        self.assertIsNone(match, f"{kind}: {match and text[max(0, match.start() - 80):match.end() + 20]!r}")

    def test_what_the_human_sees_carries_no_forbidden_identifier(self):
        for machine in MACHINES:
            with self.subTest(machine=machine):
                mac = record(machine)
                for value in forbidden(machine):
                    self.assertNotIn(value.lower(), mac.output.lower())

    def test_device_serials_and_bluetooth_addresses_never_reach_a_recording_or_a_report(self):
        for stdout, values in DEVICE_SERIALS.values():
            for value in values:
                self.assertIn(value, stdout)  # the fixtures really hold what must not come out
        machine = RecordedHost({
            "recording_version": 1, "description": "device identifiers", "source": "tests",
            "commands": [{"argv": list(argv), "returncode": 0, "stdout": stdout, "stderr": ""} for argv, (stdout, _) in DEVICE_SERIALS.items()],
            "files": {path: {"text": text} for path, text in SERIAL_FILES.items()},
            "dirs": {},
        })
        recorder = RecordingHost(machine)
        recorder.capture_sources(list(DEVICE_SERIALS))
        for path in SERIAL_FILES:
            recorder.read_file(path)
        saved = recorder.recording(privacy.Scrubber())
        evidence = [line for stdout, _ in DEVICE_SERIALS.values() for line in stdout.splitlines()]
        contract = ReportPrivacyContractTest()
        enforced = privacy.enforce(contract.report([contract.check(evidence)]), privacy.Scrubber())
        outputs = {
            "recording": (json.dumps(saved, ensure_ascii=False), "".join(c["stdout"] for c in saved["commands"])),
            "report": (json.dumps(enforced, ensure_ascii=False), "\n".join(enforced["checks"][0]["evidence"])),
        }

        identifiers = [value for _, values in DEVICE_SERIALS.values() for value in values] + [text.strip() for text in SERIAL_FILES.values()]
        for output, (text, plain) in outputs.items():
            with self.subTest(output=output):
                for value in identifiers:
                    self.assertNotIn(value.lower(), text.lower())
                for kind, pattern in LEAK_PATTERNS.items():
                    self.assertIsNone(pattern.search(text), kind)
                # What isn't an identifier stays readable.
                for kept in ("Dell Inc. DELL U3423WE <serial> (DP-2)", '"serial": "<serial>"', "\tserial: <serial>", "Serial Number: <serial>",
                             'device.serial = "<serial>"', "alsa_card.usb-<serial>-00", "E: ID_USB_SERIAL_SHORT=<serial>",
                             '"unique_id": "<serial>"', "Device <mac> AirPods Pro", "bluez_output.<mac>.1", "/org/bluez/hci0/dev_<mac>"):
                    self.assertIn(kept, plain)
        self.assertEqual({path: saved["files"][path] for path in SERIAL_FILES}, {path: {"text": "<serial>\n"} for path in SERIAL_FILES})

    def test_device_names_hex_dumps_and_display_modes(self):
        for stdout, secrets, _ in DEVICE_NAMES.values():
            for value in secrets:
                self.assertIn(value, stdout)  # the fixtures really hold what must not come out
        machine = RecordedHost({
            "recording_version": 1, "description": "device names", "source": "tests",
            "commands": [{"argv": list(argv), "returncode": 0, "stdout": stdout, "stderr": ""} for argv, (stdout, _, _) in DEVICE_NAMES.items()],
            "files": {MACHINE_INFO[0]: {"text": MACHINE_INFO[1]}},
            "dirs": {},
        })
        recorder = RecordingHost(machine)
        recorder.capture_sources(list(DEVICE_NAMES))
        recorder.read_file(MACHINE_INFO[0])
        saved = recorder.recording(privacy.Scrubber())
        contract = ReportPrivacyContractTest()
        # In a report, each tool's output is one check's evidence, a line at a time.
        enforced = privacy.enforce(contract.report([contract.check(stdout.splitlines()) for stdout, _, _ in DEVICE_NAMES.values()]),
                                   privacy.Scrubber())
        outputs = {
            "recording": ([c["stdout"] for c in saved["commands"]], saved["files"][MACHINE_INFO[0]]["text"]),
            "report": (["\n".join(check["evidence"]) + "\n" for check in enforced["checks"]], None),
        }
        for output, (texts, machine_info) in outputs.items():
            for (argv, (_, secrets, kept)), text in zip(DEVICE_NAMES.items(), texts):
                with self.subTest(output=output, tool=" ".join(argv)):
                    for value in secrets:
                        self.assertNotIn(value.lower(), text.lower())
                    for value in kept:
                        self.assertIn(value, text)
            if machine_info is not None:
                self.assertEqual(machine_info, 'PRETTY_HOSTNAME="<device-name>"\nCHASSIS=laptop\n')
        self.assertEqual(enforced["checks"][-1]["evidence"].count(privacy.HEX_DUMP_NOTE), 1)

    def test_scrubbed_evidence_keeps_its_placeholders(self):
        text = record("m2-max-image2").written[RECORDING_FILE]
        for placeholder in ("<hostname>", "<user>", "<home>", "<ssid>", "<mac>", "<ip>", "<uuid>", "<hex>"):
            self.assertIn(placeholder, text)


class ReportPrivacyContractTest(unittest.TestCase):
    """What privacy.enforce guarantees for every report the CLI writes."""

    def report(self, checks):
        golden = json.loads(read(os.path.join(SCHEMA_DIR, "golden", "m2-max-image2.json")))
        golden["checks"] = checks
        return golden

    def check(self, evidence, **extra):
        golden = json.loads(read(os.path.join(SCHEMA_DIR, "golden", "m2-max-image2.json")))["checks"][0]
        return {**golden, "evidence": evidence, **extra}

    def test_the_allowlist_is_the_schema(self):
        def allowed(schema):
            if schema.get("type") == "object":
                return {name: allowed(sub) for name, sub in schema["properties"].items()}
            if schema.get("type") == "array" and schema["items"].get("type") == "object":
                return [allowed(schema["items"])]
            return True

        self.assertEqual(privacy.REPORT_ALLOWLIST, allowed(SCHEMA))

    def test_only_allowlisted_fields_reach_the_report(self):
        report = self.report([self.check(["ok"], raw_log="Sep 26 omarchy-m2-max kernel: ...")])
        report["machine"]["serial_number"] = "C02XXXXXXXXX"
        report["hostname"] = "omarchy-m2-max"

        enforced = privacy.enforce(report, privacy.Scrubber())

        self.assertEqual(errors(SCHEMA, enforced), [])
        self.assertNotIn("serial_number", enforced["machine"])
        self.assertNotIn("hostname", enforced)
        self.assertEqual(enforced["checks"], [self.check(["ok"])])

    def test_evidence_is_scrubbed(self):
        wifi = raw_recording("m2-max-image2")["commands"]
        lines = next(e["stdout"] for e in wifi if "--unit=iwd.service" in e["argv"]).splitlines()[:50]
        scrubber = privacy.Scrubber(hostnames=["omarchy-m2-max"], users=["kestrel"])

        enforced = privacy.enforce(self.report([self.check(lines)]), scrubber)

        text = json.dumps(enforced)
        for value in forbidden("m2-max-image2"):
            self.assertNotIn(value, text)
        self.assertEqual(errors(SCHEMA, enforced), [])

    def test_evidence_in_other_tool_formats_is_scrubbed(self):
        lines = {
            "  iSerial                 3 C02XG1ZZQ05N": "C02XG1ZZQ05N",
            "usb 1-1: SerialNumber: C02XG1ZZQ05N": "C02XG1ZZQ05N",
            "\tssid Kookaburra Nest": "Kookaburra",
            "iwd: station: Connected to network KookaburraNest": "KookaburraNest",
            "dhcp4 (wlan0): option host_name => 'kestrels-mac'": "kestrels-mac",
            "Sat 2026-09-26 08:40:28 AEST kestrels-mac kernel: PM: suspend entry (s2idle)": "kestrels-mac",
            "Expecting device /dev/disk/by-uuid/4F4D-5801...": "4F4D-5801",
            "root=UUID=1A2B-3C4D rw": "1A2B-3C4D",
            "Accepted publickey for kestrel from 10.0.0.9 port 51234 ssh2: ED25519 SHA256:40+oZmQAparc9et6IwaI28X2SMonCFaVfvqpYqxCHkg": "kestrel",
            "rsync kestrel@build.example.net:/srv": "kestrel@",
        }

        enforced = privacy.enforce(self.report([self.check(list(lines))]), privacy.Scrubber())

        evidence = enforced["checks"][0]["evidence"]
        for line, identifier in zip(evidence, lines.values()):
            self.assertNotIn(identifier, line)
        self.assertNotIn("40+oZmQA", " ".join(evidence))
        self.assertIn("suspend entry (s2idle)", evidence[5])

    def test_placeholder_serials_are_scrubbed_where_they_are_but_nowhere_else(self):
        lines = ['{"name": "eDP-1", "serial": "0x0000"}', "E: ID_SERIAL_SHORT=12345", "E: ID_SERIAL_SHORT=0000000000",
                 "00:00.0 PCI bridge [0604]: Apple Inc. Device [106b:1003], Class 0x0000", "read 12345 bytes from 0000000000 blocks"]

        evidence = privacy.enforce(self.report([self.check(lines)]), privacy.Scrubber())["checks"][0]["evidence"]

        self.assertEqual(evidence[:3], ['{"name": "eDP-1", "serial": "<serial>"}', "E: ID_SERIAL_SHORT=<serial>", "E: ID_SERIAL_SHORT=<serial>"])
        self.assertEqual(evidence[3:], lines[3:])

    def test_a_bluetooth_controller_named_after_the_host_stays_the_hostname(self):
        lines = ["Controller F0:C0:7B:98:E6:D4 omarchy-m2-max [default]", "Sep 26 08:40:28 omarchy-m2-max kernel: PM: suspend entry (s2idle)"]

        evidence = privacy.enforce(self.report([self.check(lines)]), privacy.Scrubber(hostnames=["omarchy-m2-max"]))["checks"][0]["evidence"]

        self.assertEqual(evidence, ["Controller <mac> <hostname> [default]", "Sep 26 08:40:28 <hostname> kernel: PM: suspend entry (s2idle)"])

    def test_a_short_common_account_name_leaves_the_model_alone(self):
        report = self.report([self.check(["kernel: Machine model: Apple MacBook Pro (16-inch, M2 Max, 2023)"])])

        enforced = privacy.enforce(report, privacy.Scrubber(users=["max"], hostnames=["mac"]))

        self.assertEqual(enforced["machine"]["model"], "Apple MacBook Pro (16-inch, M2 Max, 2023)")
        self.assertEqual(enforced["checks"][0]["evidence"], ["kernel: Machine model: Apple MacBook Pro (16-inch, M2 Max, 2023)"])

    def test_evidence_is_at_most_64_kib_per_report(self):
        line = "x" * 500
        report = self.report([self.check([line] * 50) for _ in range(5)])  # 125 000 bytes

        enforced = privacy.enforce(report, privacy.Scrubber())

        self.assertLessEqual(privacy.evidence_bytes(enforced), 64 * 1024)
        flat = [line for check in enforced["checks"] for line in check["evidence"]]
        self.assertEqual(flat[-1], privacy.TRUNCATED_NOTE)
        self.assertEqual(len(enforced["checks"]), 5)
        self.assertEqual(errors(SCHEMA, enforced), [])

    def test_evidence_is_text_only_and_within_the_schema_limits(self):
        report = self.report([self.check(["PNG\x00\x1a binary", "caf�", 42, "y" * 900] + ["z"] * 60)])

        enforced = privacy.enforce(report, privacy.Scrubber())

        evidence = enforced["checks"][0]["evidence"]
        self.assertEqual(evidence[:3], [privacy.NON_TEXT_NOTE] * 3)
        self.assertEqual(len(evidence[3]), 500)
        self.assertEqual(len(evidence), 50)
        self.assertEqual(errors(SCHEMA, enforced), [])


if __name__ == "__main__":
    unittest.main()
