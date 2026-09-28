"""Seam A: the whole CLI against a recorded host with scripted answers.

Tests feed a recording and the human's answers in, and assert only on what
comes out: the exit status, what the human saw, the report written and what
was uploaded.
"""

from __future__ import annotations

import glob
import json
import os
import unittest

from omarchy_m_test.app import main
from omarchy_m_test.consent import CONSENT_VERSION
from omarchy_m_test.host import HttpResponse, NetworkError
from omarchy_m_test.recording import ENDED, EOF, RecordedHost, RecordingMiss
from tests.desktop import UNANSWERED
from tests.schema_validator import errors

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SCHEMA_DIR = os.path.join(REPO, "schema")
RECORDINGS = os.path.join(HERE, "recordings")
REPORT_FILE = "omarchy-m-test-report.json"
SITE = "http://localhost:3000"

ENTER = ""


def read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


SCHEMA = json.loads(read(os.path.join(SCHEMA_DIR, "report-v1.schema.json")))


def golden(name: str) -> str:
    return read(os.path.join(SCHEMA_DIR, "golden", f"{name}.json"))


def host(recording: str, answers=(), responses=()) -> RecordedHost:
    return RecordedHost.load(os.path.join(RECORDINGS, f"{recording}.json"), answers=list(answers), responses=list(responses))


def created(report_id: str = "abc123") -> HttpResponse:
    return HttpResponse(201, json.dumps({
        "id": report_id,
        "report_url": f"{SITE}/reports/{report_id}",
        "deletion_url": f"{SITE}/reports/{report_id}/deletion?token=secret",
    }))


class FullRunTest(unittest.TestCase):
    def test_m2_max_run_writes_shows_and_uploads_the_golden_report(self):
        mac = host("m2-max-image2", answers=[ENTER, *UNANSWERED, "y"], responses=[created()])

        status = main(["--site", SITE], mac)

        expected = golden("m2-max-image2")
        self.assertEqual(status, 0)
        self.assertEqual(mac.written, {REPORT_FILE: expected})
        self.assertEqual(errors(SCHEMA, json.loads(expected)), [])
        self.assertEqual([(p.url, p.body) for p in mac.posts], [(f"{SITE}/api/v1/reports", expected)])
        self.assertIn(f"{SITE}/reports/abc123", mac.output)
        self.assertIn(f"{SITE}/reports/abc123/deletion?token=secret", mac.output)
        self.assertEqual(mac.unused_script(), [])

    def test_the_exact_report_is_shown_before_the_upload_prompt(self):
        mac = host("m2-max-image2", answers=[ENTER, *UNANSWERED, "y"], responses=[created()])

        main(["--site", SITE], mac)

        shown_report = next(i for i, e in enumerate(mac.transcript) if e == ("show", golden("m2-max-image2")))
        upload_prompt = next(i for i, e in enumerate(mac.transcript) if e[0] == "prompt" and "Upload" in e[1])
        self.assertLess(shown_report, upload_prompt)

    def test_report_records_the_consent_version(self):
        mac = host("m2-max-image2", answers=[ENTER, ENDED], responses=[])

        main(["--dry-run"], mac)

        self.assertEqual(json.loads(mac.written[REPORT_FILE])["consent_version"], CONSENT_VERSION)
        self.assertEqual(CONSENT_VERSION, 6)  # the disclaimer says a run offers the tester sign-in once

    def test_output_option_chooses_where_the_report_is_written(self):
        mac = host("m2-max-image2", answers=[ENTER, ENDED])

        main(["--dry-run", "--output", "/tmp/r.json"], mac)

        self.assertEqual(list(mac.written), ["/tmp/r.json"])


class DryRunTest(unittest.TestCase):
    def test_dry_run_writes_the_golden_report_and_never_uploads(self):
        mac = host("m2-max-image2", answers=[ENTER, ENDED])

        status = main(["--dry-run", "--site", SITE], mac)

        self.assertEqual(status, 0)
        self.assertEqual(mac.written, {REPORT_FILE: golden("m2-max-image2")})
        self.assertEqual(mac.posts, [])
        self.assertFalse(any(e[0] == "prompt" and "Upload" in e[1] for e in mac.transcript))
        self.assertIn("not uploaded", mac.output)


class UploadDeclinedOrFailedTest(unittest.TestCase):
    def test_answering_no_keeps_the_report_local(self):
        for answer in ("n", "nope", EOF):
            with self.subTest(answer=answer):
                mac = host("m2-max-image2", answers=[ENTER, *UNANSWERED, answer])

                status = main(["--site", SITE], mac)

                self.assertEqual(status, 0)
                self.assertEqual(mac.posts, [])
                self.assertIn(REPORT_FILE, mac.written)

    def test_enter_at_the_upload_question_uploads(self):
        mac = host("m2-max-image2", answers=[ENTER, *UNANSWERED, ENTER], responses=[created()])

        self.assertEqual(main(["--site", SITE], mac), 0)
        self.assertIn(f"Upload this report to {SITE}? [Y/n] ", [e[1] for e in mac.transcript if e[0] == "prompt"])
        self.assertEqual(len(mac.posts), 1)

    def test_a_rejected_upload_shows_the_sites_reason(self):
        rejected = HttpResponse(422, json.dumps({"error": "Report does not match schema v1.", "details": ["checks is missing"]}))
        mac = host("m2-max-image2", answers=[ENTER, *UNANSWERED, "y"], responses=[rejected])

        status = main(["--site", SITE], mac)

        self.assertEqual(status, 3)
        self.assertIn("Report does not match schema v1.", mac.output)
        self.assertIn("checks is missing", mac.output)

    def test_an_unreachable_site_fails_cleanly(self):
        class Unreachable(RecordedHost):
            def post_json(self, url, body):
                super().post_json(url, body)
                raise NetworkError("connection refused")

        mac = Unreachable(host("m2-max-image2").recording, answers=[ENTER, *UNANSWERED, "y"], responses=[created()])

        status = main(["--site", SITE], mac)

        self.assertEqual(status, 3)
        self.assertIn("couldn't reach", mac.output)


class DisclaimerTest(unittest.TestCase):
    def test_enter_or_y_accepts_anything_else_cancels_without_running(self):
        for answer in ("y", "Yes", " "):
            with self.subTest(answer=answer):
                mac = host("m2-max-image2", answers=[answer, ENDED])

                self.assertEqual(main(["--dry-run"], mac), 0)
                self.assertNotIn("Cancelled", mac.output)
        for answer in ("n", "q", "no", "yes please", EOF):
            with self.subTest(answer=answer):
                mac = host("m2-max-image2", answers=[answer])

                status = main(["--site", SITE], mac)

                self.assertEqual(status, 1)
                self.assertIn("Cancelled. Nothing was run.", mac.output)
                self.assertNotIn("system.identity", mac.output)
                self.assertEqual(mac.written, {})
                self.assertEqual(mac.posts, [])

    def test_the_disclaimer_says_what_it_never_does(self):
        mac = host("m2-max-image2", answers=["n"])

        main([], mac)

        self.assertIn("never does", mac.output)
        self.assertIn("Reboot your Mac", mac.output)


class NonAppleTest(unittest.TestCase):
    def test_non_apple_machines_are_refused_before_the_disclaimer(self):
        for recording in ("x86-laptop", "raspberry-pi-4"):
            with self.subTest(recording=recording):
                machine = host(recording)

                status = main([], machine)

                self.assertEqual(status, 2)
                self.assertIn("only runs on Apple Silicon Macs", machine.output)
                self.assertEqual([e for e in machine.transcript if e[0] == "prompt"], [])
                self.assertEqual(machine.written, {})


class RecordedHostTest(unittest.TestCase):
    """The harness itself must fail loudly rather than let a test pass by accident."""

    def test_unrecorded_interactions_raise(self):
        mac = host("m2-max-image2")
        with self.assertRaises(RecordingMiss):
            mac.read_file("/etc/hostname")
        with self.assertRaises(RecordingMiss):
            mac.run(["cat", "/etc/hostname"])
        with self.assertRaises(RecordingMiss):
            mac.list_dir("/root")
        with self.assertRaises(RecordingMiss):
            mac.prompt("anything?")

    def test_every_recording_loads(self):
        for path in glob.glob(os.path.join(RECORDINGS, "*.json")):
            with self.subTest(recording=os.path.basename(path)):
                RecordedHost.load(path)


class GoldenReportsTest(unittest.TestCase):
    def test_every_golden_report_validates_against_the_schema(self):
        paths = glob.glob(os.path.join(SCHEMA_DIR, "golden", "*.json"))
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(golden=os.path.basename(path)):
                self.assertEqual(errors(SCHEMA, json.loads(read(path))), [])

    def test_the_schema_rejects_fields_outside_the_allowlist(self):
        report = json.loads(golden("m2-max-image2"))
        report["machine"]["serial_number"] = "C02XXXXXXXXX"
        self.assertIn("$.machine: unexpected property serial_number", errors(SCHEMA, report))


if __name__ == "__main__":
    unittest.main()
