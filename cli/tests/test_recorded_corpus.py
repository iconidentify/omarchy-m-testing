"""Seam A: record mode, the recorded-Mac corpus and privacy.

The whole CLI runs in record mode against the real M1 and M2 evidence in
tests/corpus/ (kernel logs, device-tree dump, first-boot, Wi-Fi and lid
journals, uname, PCI, input devices and addresses), exactly as it would on
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
from omarchy_m_test.recording import ENDED, RECORDED_SOURCES, RecordedHost
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
}

# What each machine's raw evidence is known to contain (the M1 evidence has
# no MAC address, home path, UUID or long hex id).
CORPUS_HOLDS = {
    "m2-max-image2": ("MAC address", "IPv4 address", "IPv6 address", "UUID", "long hex identifier", "home path"),
    "m1-pro-mx-mac": ("IPv4 address", "IPv6 address"),
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

                replay = RecordedHost(json.loads(recorded.written[RECORDING_FILE]), answers=[ENTER, ENDED])
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
