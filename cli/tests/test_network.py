"""Seam A: the Network section's live checks, the Wi-Fi first join and Bluetooth pairing, with scripted answers.

The whole CLI runs against the recorded M2 Max, only the Network section
(tests/live_mac.py models its Wi-Fi driver, its NetworkManager connection
and what the join watch sees after a reload, so the tests can check the
driver and the connection were put back). The recorded first-join failure is
the M2's own (6 GHz, connected, no lease); the good first join is what
omarchy-mac's check saw with its fix (5 GHz, an address in 2.6 s).
"""

from __future__ import annotations

import copy
import json
import unittest

from omarchy_m_test import changes, network
from omarchy_m_test.app import main
from omarchy_m_test.host import bundled_argv
from omarchy_m_test.recording import ENDED, EOF
from omarchy_m_test.safety import refusal
from tests.live_mac import (
    CONNECTION, FAILED_JOIN, LOAD, RECONNECT, UEVENT, UNLOAD, WATCH, WLAN, LiveMac, MacState, live_recording,
)
from tests.test_audio_display import SECTIONS, answer, run
from tests.test_interactive import ARGS, ENTER, check, prompts, report

RELOAD_PROMPT = network.RELOAD_QUESTION + " [y/N] "
PAIRING_PROMPT = network.PAIRING_QUESTION + " [y/n/s] "
FIRST_JOIN = network.FIRST_JOIN


def first_join(answers=("s", "y"), **kwargs) -> tuple[LiveMac, dict]:
    host = run("network", answers, **kwargs)
    return host, check(host, FIRST_JOIN)


def with_mac_check_line(rec: dict, old: str, new: str) -> dict:
    rec = copy.deepcopy(rec)
    entry = next(e for e in rec["commands"] if e["argv"] == bundled_argv("mac-check"))
    assert old in entry["stdout"]
    entry["stdout"] = entry["stdout"].replace(old, new)
    return rec


# -- the first join after the driver starts ---------------------------------------------

class FirstJoinTest(unittest.TestCase):
    def assert_put_back(self, host: LiveMac) -> None:
        self.assertTrue(host.state.wifi_driver)
        self.assertTrue(host.state.connection_active)

    def test_a_good_first_join_records_when_it_joined_and_when_traffic_arrived(self):
        host, result = first_join()

        self.assertEqual((result["kind"], result["status"]), ("automatic", "pass"))
        self.assertEqual(result["classification"]["outcome"], "works")
        self.assertEqual((result["classification"]["feature"], result["classification"]["layer"]), ("wifi-5ghz-first-join", "omarchy"))
        self.assertEqual(result["evidence"], [
            "before: associated on 5 GHz (5240 MHz) with an address, on a NetworkManager connection that connects automatically",
            "reloaded the Wi-Fi driver (brcmfmac); watched the rejoin for 45 s",
            "first join: associated 2.12 s after the driver loaded",
            "first join: an address (traffic) arrived 2.60 s after the driver loaded, 0.48 s after associating",
            "band: 5 GHz (5240 MHz)",
            "joins: 1",
        ])
        commands = host.commands_run
        self.assertLess(commands.index(UNLOAD), commands.index(LOAD))
        self.assertLess(commands.index(LOAD), commands.index(WATCH))
        self.assertLess(host.output.index("Wi-Fi drops now"), host.output.index(RELOAD_PROMPT))
        self.assert_put_back(host)

    def test_the_recorded_first_join_failure_connects_without_traffic_and_fails(self):
        host, result = first_join(state=MacState(join=FAILED_JOIN))

        self.assertEqual((result["status"], result["classification"]["outcome"]), ("fail", "fails"))
        self.assertEqual(result["evidence"][2:], [
            "first join: associated 1.87 s after the driver loaded",
            "first join: associated but no address (no traffic) in the 43.13 s it stayed associated",
            "band at the end: 6 GHz (6135 MHz)",
            "joins: 1",
        ])
        # The connection didn't come back by itself: the restorer brought it up once the section ended.
        self.assertEqual(host.commands_run[-1], RECONNECT)
        self.assert_put_back(host)

    def test_a_first_join_that_drops_before_any_traffic_fails_even_if_a_later_join_gets_an_address(self):
        join = "up 150\ndown 900\nup 1100\naddress 1400\nfreq 5240\nconnection same\n"
        _, result = first_join(state=MacState(join=join))

        self.assertEqual(result["status"], "fail")
        self.assertIn("first join: no address (no traffic) before it dropped 9.00 s after the driver loaded", result["evidence"])
        self.assertIn("join 2: an address arrived 14.00 s after the driver loaded", result["evidence"])
        self.assertIn("joins: 2", result["evidence"])

    def test_a_stalled_first_join_still_fails_when_networkmanager_then_joins_another_network(self):
        # boot-1-failure.log's shape: connected, 43 s without a lease, then another saved network got one.
        join = "up 20\ndown 4300\nup 4310\naddress 4360\nfreq 2412\nconnection other\n"
        host, result = first_join(state=MacState(join=join))

        self.assertEqual(result["status"], "fail")
        self.assertIn("first join: no address (no traffic) before it dropped 43.00 s after the driver loaded", result["evidence"])
        self.assertIn("band at the end: 2.4 GHz (2412 MHz)", result["evidence"])

    def test_a_built_in_driver_isnt_reloaded(self):
        rec = live_recording()
        rec["files"]["/sys/module/brcmfmac/initstate"] = None
        host, result = first_join(rec=rec)

        self.assert_not_reloaded(host, result, "brcmfmac isn't loaded as a module", asked=True)

    def test_no_join_at_all_fails(self):
        host, result = first_join(state=MacState(join="timeout 4500\nconnection other\n"))

        self.assertEqual(result["status"], "fail")
        self.assertIn("no join: Wi-Fi didn't associate within 45 s of the driver loading", result["evidence"][-1])
        self.assert_put_back(host)

    def test_joining_another_saved_network_is_skipped_and_the_original_brought_back(self):
        host, result = first_join(state=MacState(join="up 200\naddress 300\nfreq 2412\nconnection other\n"))

        self.assertEqual(result["status"], "skip")
        self.assertIn("NetworkManager joined another saved network", result["evidence"][-1])

    def test_the_connection_is_known_by_uuid_only_and_never_reported(self):
        host, _ = first_join()

        self.assertNotIn(CONNECTION, json.dumps(report(host)))
        self.assertNotIn("<uuid>", json.dumps(report(host)))

    def assert_not_reloaded(self, host: LiveMac, result: dict, reason: str, asked: bool = False) -> None:
        self.assertEqual((result["kind"], result["status"]), ("automatic", "skip"))
        self.assertIn(reason, result["evidence"][-1])
        self.assertNotIn(UNLOAD, host.commands_run)
        self.assertEqual(RELOAD_PROMPT in prompts(host), asked)
        self.assert_put_back(host)

    def test_never_over_ssh_so_never_over_an_ssh_session_on_this_wi_fi(self):
        for env in ({"SSH_CONNECTION": "192.168.0.20 51514 192.168.0.106 22"}, {"SSH_TTY": "/dev/pts/1"}):
            with self.subTest(env=env):
                host, result = first_join(answers=["s"], rec=live_recording(env))

                self.assert_not_reloaded(host, result, "running over SSH")

    def test_never_from_a_remote_session_or_without_a_local_seat(self):
        for session, reason in (
            ({"Remote": "yes", "Seat": "", "Active": "yes"}, "running over SSH"),
            ({"Remote": "no", "Seat": "", "Active": "yes"}, "no local desktop session"),
            ({"Remote": "no", "Seat": "seat0", "Active": "no"}, "no local desktop session"),
            (None, "no local desktop session"),
        ):
            with self.subTest(session=session):
                host, result = first_join(answers=["s"], state=MacState(session=session))

                self.assert_not_reloaded(host, result, reason)

    def test_without_a_rejoin_path_the_driver_is_left_alone(self):
        not_managed = answer(live_recording(), ["nmcli", "-g", "connection.autoconnect", "connection", "show", CONNECTION], stdout="no\n")
        other_driver = live_recording()
        other_driver["files"][UEVENT] = {"text": "DRIVER=mt7921e\n"}
        no_address = answer(live_recording(), changes.addresses_argv(WLAN), 1, "0\n")
        for rec, state, reason in (
            (not_managed, None, "isn't set to connect automatically"),
            (other_driver, None, "no Wi-Fi interface driven by brcmfmac"),
            (no_address, None, "Wi-Fi has no IPv4 address now"),
            (live_recording(), MacState(wifi_up=False), "Wi-Fi isn't connected"),
            (live_recording(), MacState(connection_active=False), "NetworkManager hasn't activated a Wi-Fi connection"),
        ):
            with self.subTest(reason=reason):
                host, result = first_join(answers=["s"], rec=rec, state=state)

                self.assertEqual(result["status"], "skip")
                self.assertIn(reason, result["evidence"][-1])
                self.assertNotIn(UNLOAD, host.commands_run)
                self.assertNotIn(RELOAD_PROMPT, prompts(host))

    def test_on_24_ghz_it_asks_for_a_5_ghz_network_instead(self):
        host, result = first_join(answers=["s"], state=MacState(frequency="2437"))

        self.assert_not_reloaded(host, result, "needs a 5 GHz network")
        self.assertIn("before: associated on 2.4 GHz (2437 MHz)", result["evidence"][0])

    def test_declining_the_reload_skips_it(self):
        for reply in ("n", "", EOF):
            with self.subTest(reply=reply):
                host, result = first_join(answers=["s", reply])

                self.assert_not_reloaded(host, result, "you chose not to reload the Wi-Fi driver", asked=True)

    def test_without_sudo_off_a_terminal_nothing_is_reloaded(self):
        host, result = first_join(state=MacState(sudo_cached=False))

        self.assert_not_reloaded(host, result, "needs sudo, and it wasn't given", asked=True)

    def test_a_driver_that_wont_load_again_fails_and_its_restorer_tries_again(self):
        host, result = first_join(state=MacState(driver_loads=False))

        self.assertEqual(result["status"], "fail")
        self.assertIn("modprobe couldn't load the Wi-Fi driver again (modprobe: ERROR", result["evidence"][-1])
        self.assertNotIn(WATCH, host.commands_run)
        self.assertEqual(host.commands_run.count(LOAD), 2)
        self.assertIn("the Wi-Fi driver (loaded again)", host.output)  # the failed restorer is reported

    def test_ctrl_c_while_the_driver_is_unloaded_loads_it_and_brings_the_connection_back(self):
        class Interrupted(LiveMac):
            def run(self, argv):
                if list(argv) == ["sleep", "1"]:
                    raise KeyboardInterrupt
                return super().run(argv)

        host = Interrupted(live_recording(), answers=[ENTER, "s", "y"])
        self.assertEqual(main(ARGS, host, sections=(SECTIONS["network"],)), 130)

        self.assertEqual(host.commands_run[-2:], [LOAD, RECONNECT])
        self.assertTrue(host.state.wifi_driver)
        self.assertTrue(host.state.connection_active)

    def test_its_commands_pass_the_safety_guard(self):
        for argv in (UNLOAD, LOAD, WATCH, RECONNECT, changes.frequency_argv(WLAN), changes.addresses_argv(WLAN), network.PAIRED):
            with self.subTest(argv=argv[:3]):
                self.assertIsNone(refusal(argv))


# -- Bluetooth pairing --------------------------------------------------------------------

class BluetoothPairingTest(unittest.TestCase):
    def pairing(self, answers, **kwargs) -> tuple[LiveMac, dict]:
        host = run("network", [*answers, ENDED], **kwargs)
        return host, check(host, network.PAIRING)

    def test_pairing_a_device_is_confirmed_by_the_human_with_the_paired_count_as_evidence(self):
        host, result = self.pairing(["y paired my headphones"], state=MacState(paired=[1, 2]))

        self.assertEqual((result["kind"], result["status"], result["classification"]["outcome"]), ("human", "pass", "works"))
        self.assertEqual(result["classification"]["feature"], "bluetooth")
        self.assertEqual(result["evidence"], [
            "Bluetooth controller powered (mac-check)",
            f"asked: {network.PAIRING_QUESTION}",
            "answer: yes",
            "note: paired my headphones",
            "paired devices: 1 before, 2 after",
        ])
        self.assertIn("The device stays paired", host.output)
        # Asked while Wi-Fi is still up: before the driver reload.
        self.assertLess(prompts(host).index(PAIRING_PROMPT), prompts(host).index(RELOAD_PROMPT))

    def test_a_device_that_wont_pair_fails(self):
        _, result = self.pairing(["n it never showed up"], state=MacState(paired=[0]))

        self.assertEqual((result["status"], result["classification"]["outcome"]), ("fail", "fails"))
        self.assertIn("paired devices: 0 before, 0 after", result["evidence"])

    def test_without_a_powered_controller_nothing_is_asked(self):
        rec = with_mac_check_line(live_recording(), "PASS  bluetooth        controller powered", "FAIL  bluetooth        controller present but not powered")
        host, result = self.pairing([], rec=rec)

        self.assertEqual((result["kind"], result["status"]), ("human", "skip"))
        self.assertEqual(result["evidence"], ["skipped: no powered Bluetooth controller (see network.bluetooth)"])
        self.assertNotIn(PAIRING_PROMPT, prompts(host))
        self.assertNotIn(network.PAIRED, host.commands_run)

    def test_a_count_bluez_cant_give_is_said_so(self):
        _, result = self.pairing(["y"], rec=answer(live_recording(), network.PAIRED, 127, stderr="sh: bluetoothctl: command not found\n"))

        self.assertEqual(result["status"], "pass")
        self.assertIn("paired devices: couldn't be counted", result["evidence"])


# -- the golden runs ---------------------------------------------------------------------

class GoldenTest(unittest.TestCase):
    def test_the_recorded_runs_over_ssh_skip_the_first_join_and_ask_for_pairing(self):
        from tests.test_audio_display import golden

        for name in ("m2-max-image2", "m1-pro-mx-mac"):
            with self.subTest(name=name):
                checks = golden(name)
                self.assertEqual(checks[FIRST_JOIN]["evidence"], ["skipped: running over SSH, where it could cut the connection"])
                self.assertEqual(checks[network.PAIRING]["kind"], "human")
                self.assertIn("answer: none (counted as skipped)", checks[network.PAIRING]["evidence"])


if __name__ == "__main__":
    unittest.main()
