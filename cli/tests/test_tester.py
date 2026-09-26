"""Seam A: tester sign-in (omarchy-m-test --sign-in), GitHub's device flow.

GitHub's answers are scripted form POSTs; the site's answer is a scripted
upload response. The sign-in the CLI sends the site is signed for real, with
the fixture key, and must be exactly the shared golden sign-in
(schema/golden/sign-in/), which Seam B posts to the site. After changing what
a sign-in carries, write it again from cli/: python3 -m tests.test_tester regenerate
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

from omarchy_m_test import tester
from omarchy_m_test.app import main
from omarchy_m_test.host import HttpResponse, NetworkError
from omarchy_m_test.recording import INTERRUPT, RecordedHost
from tests.test_seam_a import SCHEMA_DIR, SITE, read
from tests.test_signing import signing_mac, with_fixture_key

GOLDEN_SIGN_IN = os.path.join(SCHEMA_DIR, "golden", "sign-in", "tester-sign-in.json")
# The token GitHub hands the golden sign-in (Seam B's fake GitHub knows it).
TOKEN = "gho_goldenTesterToken0123456789"
DEVICE_CODE = "3584d83530557fdd1f46af8289938c8ef79f9dc5"


def github(status: int = 200, **body) -> HttpResponse:
    return HttpResponse(status, json.dumps(body))


def device(**overrides) -> HttpResponse:
    return github(**{"device_code": DEVICE_CODE, "user_code": "WDJB-MJHT", "verification_uri": "https://github.com/login/device",
                     "expires_in": 900, "interval": 5, **overrides})


PENDING = github(error="authorization_pending")
GRANTED = github(access_token=TOKEN, token_type="bearer", scope="")


def bound(login: str = "maralcbr", allowlisted: bool = True) -> HttpResponse:
    return HttpResponse(201, json.dumps({"login": login, "tester": allowlisted, "message": "..."}))


def verifies(document: dict, namespace: str) -> bool:
    """ssh-keygen's own verdict on the signature."""
    with tempfile.TemporaryDirectory() as tmp:
        signers = os.path.join(tmp, "allowed_signers")
        with open(signers, "w", encoding="utf-8") as f:
            f.write(f"machine namespaces=\"{namespace}\" {document['signature']['public_key']}\n")
        sig = os.path.join(tmp, "sign-in.sig")
        with open(sig, "w", encoding="utf-8") as f:
            f.write(document["signature"]["signature"] + "\n")
        unsigned = {k: v for k, v in document.items() if k != "signature"}
        message = json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        done = subprocess.run(["ssh-keygen", "-Y", "verify", "-f", signers, "-I", "machine", "-n", namespace, "-s", sig],
                              input=message, capture_output=True)
        return done.returncode == 0


class SignInTest(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.state)
        with_fixture_key(self.state)

    def sign_in(self, forms, responses=(), answers=()) -> tuple[int, RecordedHost]:
        mac = signing_mac(self.state, answers=list(answers), responses=list(responses))
        mac.forms = list(forms)
        return main(["--sign-in", "--site", SITE], mac), mac

    def test_the_tester_enters_a_code_on_github_and_the_site_binds_the_mac(self):
        status, mac = self.sign_in([device(), PENDING, PENDING, GRANTED], [bound()])

        self.assertEqual(status, 0)
        self.assertIn("https://github.com/login/device", mac.output)
        self.assertIn("WDJB-MJHT", mac.output)
        self.assertIn("Signed in as @maralcbr. From now on this Mac's runs count as tester runs", mac.output)
        self.assertEqual(mac.unused_script(), [])

    def test_it_uses_only_the_client_id_and_polls_at_githubs_interval(self):
        _, mac = self.sign_in([device(), PENDING, GRANTED], [bound()])

        self.assertEqual(mac.form_posts[0], (tester.DEVICE_CODE_URL, {"client_id": tester.GITHUB_CLIENT_ID, "scope": ""}))
        for url, fields in mac.form_posts[1:]:
            self.assertEqual(url, tester.TOKEN_URL)
            self.assertEqual(fields, {"client_id": tester.GITHUB_CLIENT_ID, "device_code": DEVICE_CODE, "grant_type": tester.DEVICE_GRANT})
        self.assertFalse(any("secret" in name for _, fields in mac.form_posts for name in fields))
        self.assertEqual(mac.slept, [5, 5])

    def test_slow_down_makes_it_poll_less_often(self):
        _, mac = self.sign_in([device(), github(error="slow_down", interval=10), PENDING, github(error="slow_down"), GRANTED], [bound()])

        self.assertEqual(mac.slept, [5, 10, 10, 15])

    def test_the_site_gets_the_golden_sign_in_signed_with_the_machine_key(self):
        _, mac = self.sign_in([device(), GRANTED], [bound()])

        self.assertEqual([p.url for p in mac.posts], [f"{SITE}{tester.BINDING_PATH}"])
        sent = json.loads(mac.posts[0].body)
        self.assertEqual(sent, json.loads(read(GOLDEN_SIGN_IN)))
        self.assertTrue(verifies(sent, tester.NAMESPACE))
        self.assertFalse(verifies(sent, "omarchy-m-test-report"), "a sign-in must not pass for a report signature")

    def test_the_token_is_never_written_or_shown(self):
        _, mac = self.sign_in([device(), GRANTED], [bound()])

        self.assertNotIn(TOKEN, mac.output)
        self.assertFalse(any(TOKEN in text for text in mac.written.values()))
        for root, _, files in os.walk(self.state):
            for name in files:
                with open(os.path.join(root, name), "rb") as f:
                    self.assertNotIn(TOKEN.encode(), f.read())

    def test_a_handle_not_on_the_allowlist_is_bound_but_told_so(self):
        status, mac = self.sign_in([device(), GRANTED], [bound("someone", allowlisted=False)])

        self.assertEqual(status, 0)
        self.assertIn("@someone isn't on the tester allowlist yet", mac.output)

    def test_cancelling_on_github_binds_nothing(self):
        status, mac = self.sign_in([device(), PENDING, github(error="access_denied")])

        self.assertEqual(status, tester.EXIT_FAILED)
        self.assertIn("the sign-in was cancelled on GitHub", mac.output)
        self.assertEqual(mac.posts, [])

    def test_a_code_nobody_enters_expires(self):
        status, mac = self.sign_in([device(expires_in=10, interval=5), PENDING, PENDING])

        self.assertEqual(status, tester.EXIT_FAILED)
        self.assertIn("the code expired before it was entered", mac.output)
        self.assertEqual(mac.posts, [])

    def test_github_saying_the_code_expired(self):
        status, mac = self.sign_in([device(), github(error="expired_token")])

        self.assertEqual(status, tester.EXIT_FAILED)
        self.assertIn("the code expired", mac.output)

    def test_github_unreachable(self):
        status, mac = self.sign_in([NetworkError("name resolution failed")])

        self.assertEqual(status, tester.EXIT_FAILED)
        self.assertIn("couldn't reach GitHub (name resolution failed)", mac.output)

    def test_device_flow_off_or_a_bad_client_id(self):
        status, mac = self.sign_in([github(error="device_flow_disabled", error_description="Device flow is disabled")])

        self.assertEqual(status, tester.EXIT_FAILED)
        self.assertIn("GitHub refused to start the sign-in (Device flow is disabled)", mac.output)

    def test_the_sites_refusal_is_shown(self):
        refused = HttpResponse(401, json.dumps({"error": "GitHub didn't confirm the sign-in (GitHub answered HTTP 404)."}))
        status, mac = self.sign_in([device(), GRANTED], [refused])

        self.assertEqual(status, tester.EXIT_FAILED)
        self.assertIn("GitHub didn't confirm the sign-in", mac.output)

    def test_without_ssh_keygen_nothing_is_sent(self):
        mac = signing_mac(self.state)
        mac.signer = None
        mac.forms = [device(), GRANTED]

        status = main(["--sign-in", "--site", SITE], mac)

        self.assertEqual(status, tester.EXIT_FAILED)
        self.assertIn("this Mac's key can't sign the sign-in", mac.output)
        self.assertEqual(mac.posts, [])

    def test_ctrl_c_while_waiting_cancels(self):
        class Interrupted(RecordedHost):
            def sleep(self, seconds):
                raise KeyboardInterrupt

        mac = signing_mac(self.state)
        mac = Interrupted(mac.recording, signer=mac.signer, forms=[device()])

        status = main(["--sign-in", "--site", SITE], mac)

        self.assertEqual(status, tester.EXIT_FAILED)
        self.assertIn("Sign-in cancelled", mac.output)

    def test_sign_in_runs_no_checks(self):
        _, mac = self.sign_in([device(), GRANTED], [bound()])

        self.assertEqual(mac.commands_run, [])
        self.assertEqual(mac.written, {})


class TesterRunTest(unittest.TestCase):
    def test_an_upload_the_site_counts_as_a_tester_run_says_so(self):
        from tests.desktop import UNANSWERED
        from tests.test_seam_a import ENTER, created, host

        response = json.loads(created().body)
        mac = host("m2-max-image2", answers=[ENTER, *UNANSWERED, "y"], responses=[HttpResponse(201, json.dumps({**response, "tester": True}))])

        self.assertEqual(main(["--site", SITE], mac), 0)
        self.assertIn("It counts as a tester run.", mac.output)

    def test_a_community_upload_says_nothing_about_testers(self):
        from tests.desktop import UNANSWERED
        from tests.test_seam_a import ENTER, created, host

        mac = host("m2-max-image2", answers=[ENTER, *UNANSWERED, "y"], responses=[created()])

        main(["--site", SITE], mac)
        self.assertNotIn("tester", mac.output)


def regenerate() -> None:
    state = tempfile.mkdtemp()
    try:
        with_fixture_key(state)
        mac = signing_mac(state, responses=[bound()])
        mac.forms = [device(), GRANTED]
        main(["--sign-in", "--site", SITE], mac)
        with open(GOLDEN_SIGN_IN, "w", encoding="utf-8") as f:
            f.write(json.dumps(json.loads(mac.posts[0].body), indent=2) + "\n")
    finally:
        shutil.rmtree(state)


if __name__ == "__main__" and sys.argv[1:] == ["regenerate"]:
    regenerate()
