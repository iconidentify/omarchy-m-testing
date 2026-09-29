"""Seam A: which build a run is on, the image's own build record, and the M3's GPU gaps.

The build is derived from what the report already records (the Omarchy
runtime's commit and build stamp, the Aurora kernel and boot package), the
same way the site derives it: schema/golden/production/builds.json holds the
answer for every production report (reports.json, the site's public export),
and the site's tests read the same file. The image's target record adds its
allowlisted provenance keys as system.image.
"""

from __future__ import annotations

import copy
import json
import os
import unittest

from omarchy_m_test.app import main
from omarchy_m_test.recording import ENDED, RecordedHost
from tests.schema_validator import errors
from tests.test_seam_a import ENTER, RECORDINGS, REPORT_FILE, SCHEMA, SCHEMA_DIR, read

PRODUCTION = json.loads(read(os.path.join(SCHEMA_DIR, "golden", "production", "reports.json")))["reports"]
BUILDS = json.loads(read(os.path.join(SCHEMA_DIR, "golden", "production", "builds.json")))["builds"]
M2_MAX = json.loads(read(os.path.join(RECORDINGS, "m2-max-image2.json")))
SAVED = "/reports/saved.json"
TARGET = "/var/lib/omarchy/image/target"
BOOTED = "/var/lib/omarchy/image/target.booted"
M3 = "xHGd4Toq7io8CSHYYFhTjZBD"  # the MacBook Air M3 (t8122), installed outside the official installer


def production(report_id: str) -> dict:
    return next(entry["report"] for entry in PRODUCTION if entry["id"] == report_id)


def explain(report: dict) -> tuple[int, RecordedHost]:
    rec = copy.deepcopy(M2_MAX)
    rec["files"][SAVED] = {"text": json.dumps(report)}
    rec["commands"] = []  # explaining runs nothing on the machine
    mac = RecordedHost(rec, answers=[ENTER, ENDED])
    return main(["--explain", SAVED], mac), mac


def run(rec: dict) -> tuple[RecordedHost, dict]:
    mac = RecordedHost(copy.deepcopy(rec), answers=[ENTER, ENDED])
    status = main(["--dry-run"], mac)
    assert status == 0, status
    return mac, json.loads(mac.written[REPORT_FILE])


class ProductionBuildsTest(unittest.TestCase):
    def test_every_production_report_explains_with_its_build(self):
        self.assertEqual(set(BUILDS), {entry["id"] for entry in PRODUCTION})
        for entry in PRODUCTION:
            with self.subTest(entry["id"]):
                status, mac = explain(entry["report"])

                self.assertEqual(status, 0)
                self.assertIn(f"{entry['report']['machine']['model']}, build {BUILDS[entry['id']]['words']}\n", mac.output)

    def test_the_builds_tell_apart_what_the_release_number_doesnt(self):
        # Every one of these reports is "4.0.0" by its release number.
        self.assertEqual(BUILDS[M3]["words"], "f60e1ba.2026092602 (linux-aurora 7.1.12.aurora2-11, omarchy-mac-boot 20260926-1)")
        self.assertEqual(sorted({build["build"] for build in BUILDS.values()}), [
            "0052582.362956774610001", "1937418.362376005140001", "99ace40.361571887310001", "f60e1ba.2026092602",
        ])
        # The same runtime with a kernel installed by hand is a different build to look at.
        self.assertIn("linux-aurora 7.1.12.aurora2-10.90", BUILDS["GENBn2WpjrF6LYeXjKXCxZDW"]["words"])

    def test_a_reference_run_has_no_build(self):
        report = copy.deepcopy(production(M3))
        report["system"] = {**report["system"], "stack": "reference", "distro": "fedora"}

        _, mac = explain(report)

        self.assertNotIn(", build ", mac.output)


class RunShowsItsBuildTest(unittest.TestCase):
    def test_the_run_names_its_build_before_the_checks_and_with_the_report(self):
        mac, _ = run(M2_MAX)

        words = "99ace40.361571887310001 (linux-aurora 7.1.12.aurora2-2, omarchy-mac-boot 20260925-3)"
        self.assertIn(f"Build: {words}.", mac.output)
        self.assertIn(f"Build tested: {words}; omarchy-m-test ", mac.output)
        self.assertLess(mac.output.index(f"Build: {words}"), mac.output.index("Build tested:"))


class ImageRecordTest(unittest.TestCase):
    def with_target(self, text: str, path: str = TARGET) -> dict:
        rec = copy.deepcopy(M2_MAX)
        rec["files"][TARGET] = None
        rec["files"][BOOTED] = None
        rec["files"][path] = {"text": text}
        _, report = run(rec)
        self.assertEqual(errors(SCHEMA, report), [])
        return report["system"]

    def test_an_older_image_records_only_its_platform(self):
        _, report = run(M2_MAX)  # image 2: format=1, platform=apple-silicon

        self.assertEqual(report["system"]["image"], {"platform": "apple-silicon"})

    def test_the_builders_provenance_reaches_the_report(self):
        record = (
            "format=1\nplatform=apple-silicon\ncandidate_set=apple-test-9d8c39cd7182-20260928\n"
            "candidate_source_commit=9d8c39cd7182\nbuilder_commit=6f1b40d0c0ffee\nbuilder_tree_clean=yes\n"
            "image_profile=test\nbuilt=2026-09-28T05:30:11Z\npackage_set_sha256=" + "a" * 64 + "\n"
        )

        system = self.with_target(record, BOOTED)  # retired by the first boot, still read

        self.assertEqual(system["candidate_set"], "apple-test-9d8c39cd7182-20260928")
        self.assertEqual(system["image"], {
            "platform": "apple-silicon", "candidate_set": "apple-test-9d8c39cd7182-20260928",
            "candidate_source_commit": "9d8c39cd7182", "builder_commit": "6f1b40d0c0ffee", "builder_tree_clean": "yes",
            "image_profile": "test", "built": "2026-09-28T05:30:11Z", "package_set_sha256": "a" * 64,
        })

    def test_only_allowlisted_keys_with_plain_values_are_recorded(self):
        record = (
            "format=1\nplatform=apple-silicon\nhostname=omarchy-marcelo\nowner=marcelo@example.com\n"
            "image_version=2026.09.28-1\nimage_id=../../etc/passwd\nbuilt=Sep 28 2026 05:30\n"
            "builder_commit=\n# a comment\nnot a key value line\n"
        )

        system = self.with_target(record)

        self.assertEqual(system["image"], {"platform": "apple-silicon", "image_version": "2026.09.28-1"})
        text = json.dumps(system)
        for leaked in ("marcelo", "passwd", "Sep 28"):
            self.assertNotIn(leaked, text)

    def test_without_a_target_record_there_is_no_image_block(self):
        rec = copy.deepcopy(M2_MAX)
        rec["files"][TARGET] = rec["files"][BOOTED] = None

        _, report = run(rec)

        self.assertNotIn("image", report["system"])


class M3GpuGapsTest(unittest.TestCase):
    """The M3's GPU isn't supported by Asahi yet: its GPU and benchmark failures are gaps the catalogue expects."""

    GPU = ("gpu.driver", "gpu.opengl", "benchmark.opengl", "benchmark.vulkan")

    def test_the_m3s_gpu_failures_read_as_not_yet_supported(self):
        report = production(M3)

        _, mac = explain(report)

        for check_id in self.GPU:
            self.assertIn(f"GAP   {check_id}  not yet supported by Asahi (GPU)", mac.output)
            self.assertNotIn(f"FAIL  {check_id}", mac.output)
        # The report keeps the status: it failed; the outcome says it was expected.
        statuses = {check["id"]: (check["status"], check["classification"]["outcome"]) for check in report["checks"]}
        self.assertEqual({statuses[check_id] for check_id in self.GPU}, {("fail", "not-in-asahi")})

    def test_a_real_failure_on_a_supported_mac_still_reads_fail(self):
        report = copy.deepcopy(production(M3))
        report["machine"] = {**report["machine"], "soc": "t6021", "board": "j416c"}  # an M2 Max, where the GPU works

        _, mac = explain(report)

        self.assertIn("FAIL  benchmark.opengl  doesn't work, but should on this Mac (GPU)", mac.output)

    def test_vulkan_without_vulkaninfo_needs_a_gpu_bound_to_the_driver(self):
        rec = copy.deepcopy(M2_MAX)
        vulkaninfo = next(c for c in rec["commands"] if c["argv"][:1] == ["vulkaninfo"])
        vulkaninfo.update(returncode=127, stdout="", stderr="vulkaninfo: command not found\n")
        driver = next(path for path in rec["dirs"] if path.endswith("/drivers/asahi"))

        _, bound = run(rec)
        rec["dirs"][driver] = [name for name in rec["dirs"][driver] if not name.endswith(".gpu")]
        _, unbound = run(rec)

        vulkan = {name: next(c for c in report["checks"] if c["id"] == "gpu.vulkan") for name, report in (("bound", bound), ("unbound", unbound))}
        self.assertEqual(vulkan["bound"]["status"], "pass")
        self.assertEqual(vulkan["unbound"]["status"], "fail")
        self.assertIn("no GPU is bound to the asahi GPU driver, so it has no Apple GPU to use", vulkan["unbound"]["evidence"])


if __name__ == "__main__":
    unittest.main()
