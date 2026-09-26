"""Seam A: every report is signed with the Mac's own key, made silently on the first run.

The recorded Mac signs for real: its state directory is a temporary one and
signing goes through RealHost's machine_sign (ssh-keygen). The signed golden
reports (schema/golden/signed/) come from the fixture key in fixtures/, and
Seam B uploads them as they are, so the CLI and the site can't disagree on
what a signature covers. After a change to the golden reports, sign them
again from cli/: python3 -m tests.test_signing regenerate
"""

from __future__ import annotations

import copy
import glob
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest

from omarchy_m_test import signing
from omarchy_m_test.app import main
from omarchy_m_test.host import RealHost
from omarchy_m_test.recording import ENDED, RecordedHost
from tests.desktop import UNANSWERED
from tests.schema_validator import errors
from tests.test_seam_a import ENTER, RECORDINGS, REPORT_FILE, SCHEMA, SCHEMA_DIR, SITE, created, golden, read

FIXTURE_KEY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "test-machine-key")
SIGNED_GOLDEN = os.path.join(SCHEMA_DIR, "golden", "signed")
# A kernel release with every character the canonical form has to agree on.
AWKWARD_KERNEL = '7.1.12-"asahi"\\ärm/💻-ARCH'


def recording(name: str = "m2-max-image2", kernel: str | None = None) -> dict:
    with open(os.path.join(RECORDINGS, f"{name}.json"), encoding="utf-8") as f:
        rec = json.load(f)
    if kernel:
        rec = copy.deepcopy(rec)
        for command in rec["commands"]:
            if command["argv"] == ["uname", "-r"]:
                command["stdout"] = kernel + "\n"
    return rec


def signing_mac(state: str, rec: dict | None = None, answers=(ENTER, ENDED), responses=()) -> RecordedHost:
    """The recorded Mac, with its state directory at `state` and a real machine key there."""
    rec = copy.deepcopy(rec or recording())
    rec["env"] = {**rec.get("env", {}), "XDG_STATE_HOME": state}
    rec["files"] = {**rec["files"], f"{state}/omarchy-m-test/checkpoint.json": None}
    return RecordedHost(rec, answers=list(answers), responses=list(responses), signer=RealHost().machine_sign)


def with_fixture_key(state: str) -> None:
    directory = os.path.join(state, "omarchy-m-test")
    os.makedirs(directory, mode=0o700)
    for suffix in ("", ".pub"):
        shutil.copy(FIXTURE_KEY + suffix, os.path.join(directory, "machine-key" + suffix))
    os.chmod(os.path.join(directory, "machine-key"), 0o600)  # git keeps no permissions


def verifies(report: dict) -> bool:
    """ssh-keygen's own verdict on the report's signature."""
    with tempfile.TemporaryDirectory() as tmp:
        signers = os.path.join(tmp, "allowed_signers")
        with open(signers, "w", encoding="utf-8") as f:
            f.write(f"machine namespaces=\"{signing.NAMESPACE}\" {report['signature']['public_key']}\n")
        sig = os.path.join(tmp, "report.sig")
        with open(sig, "w", encoding="utf-8") as f:
            f.write(report["signature"]["signature"] + "\n")
        done = subprocess.run(
            ["ssh-keygen", "-Y", "verify", "-f", signers, "-I", "machine", "-n", signing.NAMESPACE, "-s", sig],
            input=signing.canonical(report), capture_output=True,
        )
        return done.returncode == 0


def prompts(mac: RecordedHost) -> list[str]:
    return [event[1] for event in mac.transcript if event[0] == "prompt"]


class MachineKeyTest(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.state)
        self.key = os.path.join(self.state, "omarchy-m-test", "machine-key")

    def run_cli(self, *argv: str, **kwargs) -> tuple[int, RecordedHost]:
        mac = signing_mac(self.state, **kwargs)
        return main(list(argv) or ["--dry-run"], mac), mac

    def test_the_first_run_creates_a_private_key_without_asking_anything(self):
        status, mac = self.run_cli()

        self.assertEqual(status, 0)
        self.assertEqual(stat.S_IMODE(os.stat(self.key).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(self.key)).st_mode), 0o700)
        unsigned = RecordedHost(recording(), answers=[ENTER, ENDED])
        main(["--dry-run"], unsigned)
        self.assertEqual(prompts(mac), prompts(unsigned))
        self.assertNotIn("isn't signed", mac.output)

    def test_every_report_carries_the_public_key_and_a_signature_over_it(self):
        _, mac = self.run_cli()

        report = json.loads(mac.written[REPORT_FILE])
        self.assertEqual(errors(SCHEMA, report), [])
        self.assertEqual(report["signature"]["public_key"], " ".join(read(self.key + ".pub").split()[:2]))
        self.assertTrue(verifies(report))
        self.assertEqual({k: v for k, v in report.items() if k != "signature"}, json.loads(golden("m2-max-image2")))
        self.assertNotIn("PRIVATE KEY", mac.output)
        self.assertNotIn(read(self.key), mac.written[REPORT_FILE])

    def test_later_runs_reuse_the_key(self):
        _, first = self.run_cli()
        key = read(self.key)
        _, second = self.run_cli()

        self.assertEqual(read(self.key), key)
        public_keys = {json.loads(mac.written[REPORT_FILE])["signature"]["public_key"] for mac in (first, second)}
        self.assertEqual(len(public_keys), 1)

    def test_a_lost_public_key_is_derived_again_from_the_private_one(self):
        _, first = self.run_cli()
        os.remove(self.key + ".pub")
        _, second = self.run_cli()

        self.assertEqual(json.loads(first.written[REPORT_FILE])["signature"]["public_key"],
                         json.loads(second.written[REPORT_FILE])["signature"]["public_key"])
        self.assertTrue(verifies(json.loads(second.written[REPORT_FILE])))

    def test_a_key_others_can_read_is_made_private_again(self):
        self.run_cli()
        os.chmod(self.key, 0o644)
        _, mac = self.run_cli()

        self.assertEqual(stat.S_IMODE(os.stat(self.key).st_mode), 0o600)
        self.assertTrue(verifies(json.loads(mac.written[REPORT_FILE])))

    def test_a_tampered_report_no_longer_verifies(self):
        _, mac = self.run_cli()
        report = json.loads(mac.written[REPORT_FILE])

        tampered = copy.deepcopy(report)
        tampered["checks"][0]["status"] = "fail"
        swapped = copy.deepcopy(report)
        swapped["machine"]["kernel"] = "7.1.13-1-ARCH"

        self.assertTrue(verifies(report))
        self.assertFalse(verifies(tampered))
        self.assertFalse(verifies(swapped))

    def test_the_signed_report_is_what_is_shown_and_uploaded(self):
        status, mac = self.run_cli("--site", SITE, answers=[ENTER, *UNANSWERED, "y"], responses=[created()])

        self.assertEqual(status, 0)
        self.assertIn(("show", mac.written[REPORT_FILE]), mac.transcript)
        self.assertEqual([post.body for post in mac.posts], [mac.written[REPORT_FILE]])

    def test_record_mode_never_records_the_key(self):
        _, mac = self.run_cli("--dry-run", "--record", "/tmp/recording.json")

        saved = mac.written["/tmp/recording.json"]
        self.assertIn("signature", json.loads(mac.written[REPORT_FILE]))
        self.assertNotIn("ssh-ed25519", saved)
        self.assertNotIn("machine-key", saved)


SIGNED_RUNS = {"m2-max-image2": None, "m2-max-image2-awkward-kernel": AWKWARD_KERNEL}


def signed_run(kernel: str | None = None) -> str:
    """The m2 Max run's report, signed by the fixture key."""
    state = tempfile.mkdtemp()
    try:
        with_fixture_key(state)
        mac = signing_mac(state, recording(kernel=kernel))
        if main(["--dry-run"], mac) != 0:
            raise AssertionError(mac.output)
        return mac.written[REPORT_FILE]
    finally:
        shutil.rmtree(state)


def regenerate() -> None:
    for name, kernel in SIGNED_RUNS.items():
        with open(os.path.join(SIGNED_GOLDEN, f"{name}.json"), "w", encoding="utf-8") as f:
            f.write(signed_run(kernel))


class SignedGoldenTest(unittest.TestCase):
    """The fixture key signs the same report the same way every time (ed25519 is deterministic)."""

    def test_the_m2_max_run_signs_to_the_signed_golden_report(self):
        self.assertEqual(signed_run(), read(os.path.join(SIGNED_GOLDEN, "m2-max-image2.json")))
        self.assertEqual(signed_run(), signed_run())

    def test_quotes_backslashes_and_non_ascii_sign_to_their_golden_report(self):
        text = signed_run(AWKWARD_KERNEL)

        self.assertEqual(json.loads(text)["machine"]["kernel"], AWKWARD_KERNEL)
        self.assertEqual(text, read(os.path.join(SIGNED_GOLDEN, "m2-max-image2-awkward-kernel.json")))

    def test_every_signed_golden_report_validates_and_verifies(self):
        paths = glob.glob(os.path.join(SIGNED_GOLDEN, "*.json"))
        self.assertEqual(sorted(os.path.basename(path) for path in paths), sorted(f"{name}.json" for name in SIGNED_RUNS))
        for path in paths:
            with self.subTest(golden=os.path.basename(path)):
                report = json.loads(read(path))
                self.assertEqual(errors(SCHEMA, report), [])
                self.assertEqual(report["signature"]["public_key"], " ".join(read(FIXTURE_KEY + ".pub").split()[:2]))
                self.assertTrue(verifies(report))


class UnsignedTest(unittest.TestCase):
    def test_without_ssh_keygen_the_report_is_written_unsigned_and_the_run_says_so(self):
        rec = recording()
        rec["env"] = {"HOME": "/home/<user>"}
        rec["files"] = {**rec["files"], "/home/<user>/.local/state/omarchy-m-test/checkpoint.json": None}
        mac = RecordedHost(rec, answers=[ENTER, ENDED])

        status = main(["--dry-run"], mac)

        self.assertEqual(status, 0)
        self.assertEqual(mac.written[REPORT_FILE], golden("m2-max-image2"))
        self.assertEqual([call[0] for call in mac.signed], ["/home/<user>/.local/state/omarchy-m-test/machine-key"])
        self.assertIn("This report isn't signed with this Mac's key: ssh-keygen isn't installed (it comes with openssh). "
                      "The site only accepts signed reports.", mac.output)

    def test_without_a_home_directory_there_is_nowhere_to_keep_the_key(self):
        mac = RecordedHost(recording(), answers=[ENTER, ENDED])

        main(["--dry-run"], mac)

        self.assertEqual(mac.signed, [])
        self.assertIn("there's no home directory to keep this Mac's key in", mac.output)


if __name__ == "__main__":
    import sys

    if sys.argv[1:] == ["regenerate"]:
        regenerate()
    else:
        unittest.main()
