"""Seam A: the newer-release notice before each run."""

from __future__ import annotations

import os
import unittest

from omarchy_m_test import TOOL_VERSION
from omarchy_m_test.app import main
from omarchy_m_test.host import HttpResponse
from omarchy_m_test.recording import RecordedHost
from omarchy_m_test.updates import INSTALL_COMMAND, LATEST_VERSION_URL

RECORDINGS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recordings")
ENTER = ""


def bumped(part: int) -> str:
    numbers = [int(n) for n in TOOL_VERSION.split(".")]
    numbers[part] += 1
    numbers[part + 1:] = [0] * (2 - part)
    return ".".join(map(str, numbers))


def run(latest=None, recording="m2-max-image2", argv=("--dry-run",)):
    fetches = {} if latest is None else {LATEST_VERSION_URL: latest}
    mac = RecordedHost.load(os.path.join(RECORDINGS, f"{recording}.json"), answers=[ENTER], fetches=fetches)
    status = main(list(argv), mac)
    return status, mac


class NewerReleaseTest(unittest.TestCase):
    def test_a_newer_release_is_announced_before_the_disclaimer_and_the_run_goes_on(self):
        status, mac = run(HttpResponse(200, bumped(1) + "\n"))

        self.assertEqual(status, 0)
        self.assertEqual(mac.gets, [LATEST_VERSION_URL])
        notice = next(i for i, e in enumerate(mac.transcript) if e[0] == "show" and bumped(1) in e[1])
        disclaimer = next(i for i, e in enumerate(mac.transcript) if e[0] == "prompt")
        self.assertLess(notice, disclaimer)
        self.assertIn(f"this is {TOOL_VERSION}", mac.output)
        self.assertIn(INSTALL_COMMAND, mac.output)
        self.assertIn("Dry run", mac.output)

    def test_patch_and_major_releases_count_and_a_v_prefix_is_fine(self):
        for latest in (bumped(2), "v" + bumped(0)):
            _, mac = run(HttpResponse(200, latest))
            self.assertIn("A newer omarchy-m-test is available", mac.output, latest)

    def test_the_same_or_an_older_release_says_nothing(self):
        for latest in (TOOL_VERSION, "0.0.1"):
            _, mac = run(HttpResponse(200, latest))
            self.assertNotIn("newer", mac.output, latest)

    def test_offline_errors_and_odd_answers_stay_silent_and_never_stop_the_run(self):
        for latest in (None, HttpResponse(404, ""), HttpResponse(200, "<html>not a version</html>")):
            status, mac = run(latest)
            self.assertEqual(status, 0)
            self.assertNotIn("newer", mac.output)
            self.assertIn("Dry run", mac.output)

    def test_it_is_checked_even_on_machines_the_tool_refuses(self):
        status, mac = run(HttpResponse(200, bumped(1)), recording="x86-laptop", argv=())

        self.assertEqual(status, 2)
        self.assertIn(bumped(1), mac.output)

    def test_explaining_a_saved_report_runs_nothing_and_looks_nothing_up(self):
        mac = RecordedHost({"recording_version": 1, "files": {"saved.json": None}}, fetches={LATEST_VERSION_URL: HttpResponse(200, bumped(1))})

        main(["--explain", "saved.json"], mac)

        self.assertEqual(mac.gets, [])


if __name__ == "__main__":
    unittest.main()
