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
# The signed --status and --sign-out requests (Seam B posts them at their requested_at: RECORDED_CLOCK).
GOLDEN_STATUS = os.path.join(SCHEMA_DIR, "golden", "sign-in", "tester-status.json")
GOLDEN_SIGN_OUT = os.path.join(SCHEMA_DIR, "golden", "sign-in", "tester-sign-out.json")
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


def answer(status: int = 200, **body) -> HttpResponse:
    return HttpResponse(status, json.dumps(body))


NOT_SIGNED_IN = answer(signed_in=False)


def signed_in(login: str = "maralcbr", allowlisted: bool = True) -> HttpResponse:
    return answer(signed_in=True, login=login, tester=allowlisted)


def link_of(mac: RecordedHost, state: str) -> dict | None:
    text = mac.written.get(f"{state}/{tester.LINK_NAME}")
    return json.loads(text) if text is not None else None


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
        self.assertIn("@someone isn't on the tester allowlist yet: ask the maintainer to add you as a tester", mac.output)

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

    def test_sign_in_runs_no_checks_and_the_mac_remembers_the_handle(self):
        _, mac = self.sign_in([device(), GRANTED], [bound()])

        self.assertEqual(mac.commands_run, [])
        self.assertEqual(list(mac.written), [f"{self.state}/{tester.LINK_NAME}"])
        self.assertEqual(link_of(mac, self.state), {"link_version": 1, "login": "maralcbr", "tester": True})
        self.assertIn(f"{self.state}/{tester.LINK_NAME}", mac.private)


OFFER_PROMPT = tester.OFFER_QUESTION + " [Y/n] "


class OfferTest(unittest.TestCase):
    """At the start of a run (after the disclaimer, before the sections), a Mac that isn't signed in is offered it once."""

    def setUp(self):
        self.state = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.state)
        with_fixture_key(self.state)
        self.link = f"{self.state}/{tester.LINK_NAME}"

    def run_offer(self, offer_answers, forms=(), responses=(), keys=(), link=None, argv=("--site", SITE)):
        from tests.desktop import UNANSWERED
        from tests.test_seam_a import ENTER

        mac = signing_mac(self.state, answers=[ENTER, *offer_answers, *UNANSWERED, "n"], responses=list(responses))
        mac.recording["files"][self.link] = link
        mac.forms, mac.keys = list(forms), list(keys)
        return main(list(argv), mac), mac

    def assert_offered_before_the_sections(self, mac):
        asked = [event[1] for event in mac.transcript if event[0] == "prompt"]
        self.assertEqual(asked[:2], ["Accept and start? [Y/n] ", OFFER_PROMPT])
        self.assertLess(mac.output.index(OFFER_PROMPT), mac.output.index("Checking "))

    def test_yes_signs_in_with_a_countdown_and_the_run_goes_on_as_a_tester_run(self):
        status, mac = self.run_offer(["y"], forms=[device(), PENDING, GRANTED], responses=[NOT_SIGNED_IN, bound()])

        self.assertEqual(status, 0)
        self.assert_offered_before_the_sections(mac)
        self.assertEqual([p.url for p in mac.posts], [f"{SITE}{tester.REQUEST_PATH}", f"{SITE}{tester.BINDING_PATH}"])
        self.assertIn("WDJB-MJHT", mac.output)
        self.assertIn("Signed in as @maralcbr. From now on this Mac's runs count as tester runs", mac.output)
        self.assertEqual(link_of(mac, self.state), {"link_version": 1, "login": "maralcbr", "tester": True})
        # Second by second, with the time left, 5 minutes at most; two polls 5 s apart.
        self.assertEqual(len(mac.waited), 10)
        self.assertEqual(mac.waited[0], (1, "  Waiting for GitHub: 5:00 left. Press any key to skip."))
        self.assertEqual(mac.waited[-1][1], "  Waiting for GitHub: 4:51 left. Press any key to skip.")
        self.assertEqual(mac.slept, [])
        self.assertIn("omarchy-m-test-report.json", " ".join(mac.written))
        self.assertEqual(mac.unused_script(), [])

    def test_an_allowlist_miss_is_said_after_signing_in(self):
        _, mac = self.run_offer(["y"], forms=[device(), GRANTED], responses=[NOT_SIGNED_IN, bound("someone", allowlisted=False)])

        self.assertIn("Signed in as @someone, but @someone isn't on the tester allowlist yet: ask the maintainer to add you as a tester",
                      mac.output)
        self.assertEqual(link_of(mac, self.state)["tester"], False)

    def test_no_is_remembered_and_never_asked_again(self):
        status, first = self.run_offer(["n"], responses=[NOT_SIGNED_IN])

        self.assertEqual(status, 0)
        self.assert_offered_before_the_sections(first)
        self.assertEqual(first.form_posts, [])
        self.assertEqual(link_of(first, self.state), {"declined": True, "link_version": 1})
        self.assertIn("omarchy-m-test --sign-in signs this Mac in any time", first.output)

        _, second = self.run_offer([], link={"text": first.written[self.link]})
        self.assertNotIn(OFFER_PROMPT, second.output)
        self.assertEqual(second.posts, [])

    def test_already_signed_in_is_never_asked(self):
        _, mac = self.run_offer([], link={"text": '{"link_version": 1, "login": "maralcbr", "tester": true}\n'})

        self.assertNotIn(OFFER_PROMPT, mac.output)
        self.assertEqual((mac.posts, mac.form_posts), ([], []))

    def test_a_mac_the_site_knows_as_signed_in_is_not_asked_and_remembers_it(self):
        # Signed in with an omarchy-m-test from before the Mac kept a record of it.
        _, mac = self.run_offer([], responses=[signed_in()])

        self.assertNotIn(OFFER_PROMPT, mac.output)
        self.assertIn("Signed in as @maralcbr (tester: yes)", mac.output)
        self.assertEqual(link_of(mac, self.state), {"link_version": 1, "login": "maralcbr", "tester": True})
        self.assertEqual(json.loads(mac.posts[0].body), json.loads(read(GOLDEN_STATUS)))

    def test_nobody_entering_the_code_gives_up_after_5_minutes_and_the_run_goes_on(self):
        status, mac = self.run_offer(["y"], forms=[device(), *[PENDING] * 60], responses=[NOT_SIGNED_IN])

        self.assertEqual(status, 0)
        self.assertEqual(len(mac.waited), tester.OFFER_WAIT_SECONDS)
        self.assertEqual(mac.waited[-1][1], "  Waiting for GitHub: 0:01 left. Press any key to skip.")
        self.assertIn("Couldn't sign in (no code was entered within 5 minutes): carrying on as a community run", mac.output)
        self.assertEqual(link_of(mac, self.state), {"declined": True, "link_version": 1})
        self.assertIn("Checking ", mac.output)
        self.assertEqual(mac.unused_script(), [])

    def test_any_key_skips_the_wait(self):
        status, mac = self.run_offer(["y"], forms=[device()], responses=[NOT_SIGNED_IN], keys=[None, None, "s"])

        self.assertEqual(status, 0)
        self.assertEqual(len(mac.waited), 3)
        self.assertEqual(mac.form_posts[1:], [])  # skipped before the first poll
        self.assertIn("Skipped signing in: this run is a community run", mac.output)
        self.assertEqual(link_of(mac, self.state), {"declined": True, "link_version": 1})
        self.assertIn("Checking ", mac.output)

    def test_github_failing_carries_on_with_one_line(self):
        _, mac = self.run_offer(["y"], forms=[NetworkError("name resolution failed")], responses=[NOT_SIGNED_IN])

        self.assertIn("Couldn't sign in (couldn't reach GitHub (name resolution failed)): carrying on as a community run", mac.output)
        self.assertIn("Checking ", mac.output)

    def test_the_site_unreachable_still_offers(self):
        _, mac = self.run_offer(["n"], responses=[answer(503, error="down")])

        self.assertIn(OFFER_PROMPT, mac.output)

    def test_a_dry_run_is_never_offered(self):
        from tests.desktop import UNANSWERED
        from tests.test_seam_a import ENTER

        mac = signing_mac(self.state, answers=[ENTER, *UNANSWERED])
        mac.recording["files"][self.link] = None
        main(["--dry-run"], mac)

        self.assertNotIn(OFFER_PROMPT, mac.output)
        self.assertEqual((mac.posts, mac.form_posts), ([], []))


class StatusAndSignOutTest(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.state)
        with_fixture_key(self.state)
        self.link = f"{self.state}/{tester.LINK_NAME}"

    def run_cli(self, flag, responses, link=None):
        mac = signing_mac(self.state, answers=[], responses=list(responses))
        mac.recording["files"][self.link] = link
        return main([flag, "--site", SITE], mac), mac

    def test_status_says_whom_the_mac_is_signed_in_as(self):
        status, mac = self.run_cli("--status", [signed_in()])

        self.assertEqual(status, 0)
        self.assertIn("Signed in as @maralcbr (tester: yes).", mac.output)
        self.assertEqual([p.url for p in mac.posts], [f"{SITE}{tester.REQUEST_PATH}"])
        sent = json.loads(mac.posts[0].body)
        self.assertEqual(sent, json.loads(read(GOLDEN_STATUS)))
        self.assertTrue(verifies(sent, tester.NAMESPACE))
        self.assertEqual(mac.commands_run, [])

    def test_status_for_a_handle_not_on_the_allowlist(self):
        _, mac = self.run_cli("--status", [signed_in("someone", allowlisted=False)])

        self.assertIn("Signed in as @someone (tester: no): ask the maintainer to add you as a tester.", mac.output)

    def test_status_not_signed_in_forgets_a_stale_record(self):
        status, mac = self.run_cli("--status", [NOT_SIGNED_IN], link={"text": '{"link_version": 1, "login": "maralcbr", "tester": true}\n'})

        self.assertEqual(status, 0)
        self.assertIn("Not signed in.", mac.output)
        self.assertIn(self.link, mac.removed)

    def test_status_without_the_site_says_what_the_mac_remembers(self):
        status, mac = self.run_cli("--status", [answer(503, error="The site is down.")],
                                   link={"text": '{"link_version": 1, "login": "maralcbr", "tester": true}\n'})

        self.assertEqual(status, tester.EXIT_FAILED)
        self.assertIn("This Mac was signed in as @maralcbr when it last checked; couldn't check with the site now: The site is down.", mac.output)

    def test_sign_out_unbinds_on_the_site_and_the_next_run_offers_again(self):
        status, mac = self.run_cli("--sign-out", [answer(signed_in=False, signed_out="maralcbr")],
                                   link={"text": '{"link_version": 1, "login": "maralcbr", "tester": true}\n'})

        self.assertEqual(status, 0)
        sent = json.loads(mac.posts[0].body)
        self.assertEqual(sent, json.loads(read(GOLDEN_SIGN_OUT)))
        self.assertTrue(verifies(sent, tester.NAMESPACE))
        self.assertIn(self.link, mac.removed)
        self.assertIn("Signed out @maralcbr: this Mac's runs no longer count as tester runs", mac.output)
        self.assertIsNone(tester.read_link(mac))

    def test_sign_out_the_site_refuses_changes_nothing(self):
        status, mac = self.run_cli("--sign-out", [answer(422, error="The request is too old.")],
                                   link={"text": '{"link_version": 1, "login": "maralcbr", "tester": true}\n'})

        self.assertEqual(status, tester.EXIT_FAILED)
        self.assertIn("Sign-out failed: The request is too old. Nothing changed", mac.output)
        self.assertNotIn(self.link, mac.removed)

    def test_sign_out_when_not_signed_in(self):
        _, mac = self.run_cli("--sign-out", [answer(signed_in=False, signed_out=None)])

        self.assertIn("This Mac wasn't signed in.", mac.output)


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
        self.assertNotIn("tester", mac.output.split("Accept and start?")[1])


def regenerate() -> None:
    state = tempfile.mkdtemp()
    try:
        with_fixture_key(state)
        mac = signing_mac(state, responses=[bound()])
        mac.forms = [device(), GRANTED]
        main(["--sign-in", "--site", SITE], mac)
        with open(GOLDEN_SIGN_IN, "w", encoding="utf-8") as f:
            f.write(json.dumps(json.loads(mac.posts[0].body), indent=2) + "\n")
        for flag, response, path in (("--status", signed_in(), GOLDEN_STATUS), ("--sign-out", answer(signed_in=False, signed_out="maralcbr"), GOLDEN_SIGN_OUT)):
            mac = signing_mac(state, answers=[], responses=[response])
            mac.recording["files"][f"{state}/{tester.LINK_NAME}"] = None
            main([flag, "--site", SITE], mac)
            with open(path, "w", encoding="utf-8") as f:
                f.write(json.dumps(json.loads(mac.posts[0].body), indent=2) + "\n")
    finally:
        shutil.rmtree(state)


if __name__ == "__main__" and sys.argv[1:] == ["regenerate"]:
    regenerate()
