"""Seam A: the Sleep section, with scripted answers: suspend and resume on the lid, clamshell, Wi-Fi and Thunderbolt after.

The whole CLI runs against the recorded M2 Max, only the Sleep section
(tests/live_mac.py models what the lid watch, the system log, the links,
Hyprland's monitors and logind answer). The recorded lid-sleep failure is the
M2's own: a USB-C display on, the lid closed, Hyprland moved to the display,
and logind suspended anyway; Thunderbolt networking didn't come back.
"""

from __future__ import annotations

import copy
import json
import re
import unittest

from omarchy_m_test import sleep
from omarchy_m_test.app import main
from omarchy_m_test.recording import ENDED, EOF
from omarchy_m_test.safety import refusal
from omarchy_m_test.host import CommandResult
from tests.desktop import CHECKPOINT, TERMINAL, omarchy_desktop
from tests.live_mac import (
    AWAKE_AGAIN, BEFORE_CLAMSHELL, BEFORE_FAILED_CLAMSHELL, BEFORE_SUSPEND, CATALOGUE_PATH, CLAMSHELL_AT, FAILED_AFTER,
    FAILED_CLAMSHELL_JOURNAL, FAILED_CLAMSHELL_WATCH, GOOD_CLAMSHELL_JOURNAL, GOOD_CLAMSHELL_WATCH, GOOD_SUSPEND_JOURNAL,
    GOOD_SUSPEND_WATCH, LOGIND_DOCKED, LOGIND_UNDOCKED, SUSPEND_AT, USB_C_DISPLAY, LiveMac, MacState, journal, links,
    live_recording, watch,
)
from tests.test_audio_display import SECTIONS, run
from tests.test_interactive import ARGS, ENTER, check, prompts, report

SUSPEND_PROMPT = sleep.SUSPEND_QUESTION + " [y/N] "
CONNECT_PROMPT = sleep.CLAMSHELL_CONNECT + " [y/N] "
CLAMSHELL_PROMPT = sleep.CLAMSHELL_QUESTION + " [y/N] "
WATCH = sleep.lid_watch_argv()


def watches(host: LiveMac) -> int:
    return sum(argv == WATCH for argv in host.commands_run)


def suspend_only(**state) -> MacState:
    """Only the suspend step runs (the clamshell step is declined)."""
    return MacState(**{"lid_watches": [GOOD_SUSPEND_WATCH], "journal": GOOD_SUSPEND_JOURNAL,
                       "links": [BEFORE_SUSPEND, AWAKE_AGAIN], "logind": [LOGIND_UNDOCKED], **state})


def clamshell_only(**state) -> MacState:
    return MacState(**{"lid_watches": [GOOD_CLAMSHELL_WATCH], "journal": GOOD_CLAMSHELL_JOURNAL,
                       "links": [BEFORE_CLAMSHELL], "logind": [LOGIND_DOCKED], **state})


def recorded_failure(**state) -> MacState:
    """The M2 Max on 2026-09-26: USB-C display on, lid closed, suspended; Thunderbolt networking stayed down."""
    return MacState(**{"lid_watches": [FAILED_CLAMSHELL_WATCH], "journal": FAILED_CLAMSHELL_JOURNAL,
                       "links": [BEFORE_FAILED_CLAMSHELL, *FAILED_AFTER], "monitors": USB_C_DISPLAY,
                       "logind": [LOGIND_UNDOCKED], **state})


def sleep_run(answers, state: MacState | None = None, **kwargs) -> LiveMac:
    return run("sleep", [*answers, ENDED], state=state, **kwargs)


# -- suspend and resume on the lid ---------------------------------------------------------

class SuspendTest(unittest.TestCase):
    def test_closing_the_lid_suspends_and_opening_it_resumes(self):
        host = sleep_run(["y", "n"], suspend_only())

        result = check(host, sleep.LID_SUSPEND)
        self.assertEqual((result["kind"], result["status"], result["classification"]["outcome"]), ("automatic", "pass", "works"))
        self.assertEqual((result["classification"]["feature"], result["classification"]["layer"]), ("suspend-sleep", "asahi"))
        self.assertEqual(result["evidence"], [
            "before: eDP-1 on",
            "lid closed: the Mac went to sleep 0.70 s later (s2idle)",
            "woke up after 12.1 s asleep, when the lid opened",
        ])
        # Warned first; the links and the checkpointed step before the lid watch; the log after it.
        self.assertLess(host.output.index("unplug any external display first"), host.output.index(SUSPEND_PROMPT))
        commands = host.commands_run
        self.assertLess(commands.index(sleep.LINKS), commands.index(WATCH))
        self.assertLess(commands.index(WATCH), commands.index(sleep.journal_argv(int(SUSPEND_AT) - 1)))

    def test_the_tool_never_suspends_the_mac_itself(self):
        host = sleep_run(["y", "y", "y"])

        self.assertEqual(watches(host), 2)
        for argv in host.commands_run:
            self.assertIsNone(refusal(argv), argv)
        for argv in (
            ["systemctl", "suspend"], ["sudo", "-n", "systemctl", "start", "suspend.target"], ["loginctl", "suspend"],
            ["systemctl", "sleep"], ["rtcwake", "-m", "mem", "-s", "10"], ["omarchy-system-suspend"],
            ["busctl", "call", "org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager", "Suspend", "b", "false"],
            ["busctl", "call", "org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager", "SuspendWithFlags", "t", "0"],
            ["dbus-send", "--system", "--dest=org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager.SleepWithFlags", "uint64:0"],
            ["dbus-send", "--system", "--dest=org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager.Suspend", "boolean:true"],
            ["sh", "-c", "echo mem > /sys/power/state"], ["sh", "-c", "echo freeze | tee /sys/power/state"],
        ):
            with self.subTest(argv=argv):
                self.assertIn("never puts the Mac to sleep", refusal(argv))
        self.assertIsNone(refusal(["rtcwake", "-m", "show"]))
        self.assertIsNone(refusal(["busctl", "get-property", "org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager", "CanSuspend"]))

    def test_nothing_is_watched_or_read_until_the_human_says_yes(self):
        for reply in ("n", "", EOF):
            with self.subTest(reply=reply):
                host = sleep_run([reply, "n"], suspend_only())

                self.assertEqual(check(host, sleep.LID_SUSPEND)["evidence"], ["skipped: you chose not to close the lid"])
                self.assertEqual(host.commands_run.count(sleep.LINKS), 0)
                self.assertEqual(watches(host), 0)
                self.assertEqual(check(host, sleep.WIFI_AFTER)["evidence"], ["skipped: the Mac didn't go to sleep and wake up in this run"])

    def test_a_mac_that_stays_awake_with_the_lid_closed_fails(self):
        stayed = watch(SUSPEND_AT + 0.5, (0, "monitors eDP-1=on"), (3.0, "closed"), (13.0, "open"))
        host = sleep_run(["y", "n"], suspend_only(lid_watches=[stayed], journal=journal(("lid-closed", SUSPEND_AT + 3.6))))

        result = check(host, sleep.LID_SUSPEND)
        self.assertEqual((result["status"], result["classification"]["outcome"]), ("fail", "fails"))
        self.assertEqual(result["evidence"][1:], [
            "logind: Docked=no, HandleLidSwitch=suspend, HandleLidSwitchDocked=ignore",
            "lid closed: the Mac didn't go to sleep in the 10.0 s it was closed",
        ])
        self.assertEqual(check(host, sleep.WIFI_AFTER)["status"], "skip")

    def test_staying_awake_is_skipped_when_it_was_meant_to(self):
        docked = watch(SUSPEND_AT + 0.5, (0, "monitors eDP-1=on HDMI-A-1=on"), (3.0, "closed"), (13.0, "open"))
        stayed = watch(SUSPEND_AT + 0.5, (0, "monitors eDP-1=on"), (3.0, "closed"), (13.0, "open"))
        no_sleep = journal(("lid-closed", SUSPEND_AT + 3.6))
        for state, why in (
            (suspend_only(lid_watches=[docked], journal=no_sleep), "an external display was on (HDMI-A-1), so the Mac is meant to stay awake"),
            (suspend_only(lid_watches=[stayed], journal=no_sleep, logind=['b false\ns "ignore"\ns "ignore"\n']),
             "logind is set not to sleep on the lid (HandleLidSwitch=ignore)"),
        ):
            with self.subTest(why=why):
                result = check(sleep_run(["y", "n"], state), sleep.LID_SUSPEND)

                self.assertEqual(result["status"], "skip")
                self.assertIn(why, result["evidence"][-1])

    def test_a_lid_that_isnt_closed_or_a_log_that_cant_be_read_is_skipped(self):
        not_closed = watch(SUSPEND_AT + 0.5, (0, "monitors eDP-1=on"), end="timeout")
        for state, why in (
            (suspend_only(lid_watches=[not_closed], journal=journal()), f"skipped: the lid wasn't closed within {sleep.CLOSE_SECONDS} s"),
            (suspend_only(journal="lines 0\n"), "skipped: the system log couldn't be read, so suspend and resume can't be seen"),
            (suspend_only(lid_watches=["start 1\nnolid 0\n"]), "skipped: logind can't say whether the lid is open or closed"),
        ):
            with self.subTest(why=why):
                result = check(sleep_run(["y", "n"], state), sleep.LID_SUSPEND)

                self.assertEqual((result["status"], result["evidence"][-1]), ("skip", why))

    def test_a_suspend_that_fails_fails(self):
        failed = journal(("lid-closed", SUSPEND_AT + 3.6), ("suspend-failed", SUSPEND_AT + 4.5))
        result = check(sleep_run(["y", "n"], suspend_only(journal=failed)), sleep.LID_SUSPEND)

        self.assertEqual(result["status"], "fail")
        self.assertIn("tried to go to sleep and failed", result["evidence"][-1])

    def test_a_mac_without_a_lid_isnt_asked(self):
        rec = live_recording()
        catalogue = json.loads(rec["files"][CATALOGUE_PATH]["text"])
        clamshell = next(f for f in catalogue["features"] if f["id"] == "clamshell")
        clamshell["models"]["j416c"] = {"omarchy": {"status": "absent"}}
        rec["files"][CATALOGUE_PATH] = {"text": json.dumps(catalogue)}

        host = sleep_run([], rec=rec)

        self.assertEqual(check(host, sleep.LID_SUSPEND)["evidence"], ["skipped: this Mac has no lid"])
        self.assertEqual(check(host, sleep.CLAMSHELL)["evidence"], ["skipped: this Mac has no lid"])
        self.assertNotIn(SUSPEND_PROMPT, prompts(host))
        self.assertEqual(watches(host), 0)


# -- clamshell ---------------------------------------------------------------------------

class ClamshellTest(unittest.TestCase):
    def clamshell(self, state: MacState, answers=("n", "y", "y")) -> tuple[LiveMac, dict]:
        host = sleep_run(list(answers), state)
        return host, check(host, sleep.CLAMSHELL)

    def test_the_recorded_m2_suspends_with_a_usb_c_display_on_and_fails(self):
        host, result = self.clamshell(recorded_failure())

        self.assertEqual((result["kind"], result["status"], result["classification"]["outcome"]), ("automatic", "fail", "fails"))
        self.assertEqual((result["classification"]["feature"], result["classification"]["layer"]), ("clamshell", "omarchy"))
        self.assertEqual(result["evidence"], [
            "before: eDP-1 on, USB-2 on",
            "logind: Docked=no, HandleLidSwitch=suspend, HandleLidSwitchDocked=ignore",
            "lid closed: the Mac went to sleep 0.74 s later (s2idle), with USB-2 on",
            "while the lid was closed: eDP-1 off, USB-2 on",
            "woke up after 31.6 s asleep",
            "logind didn't count USB-2 as an external display (DRM connector type USB, as USB-C displays are on "
            "Apple Silicon), so it wasn't docked and HandleLidSwitchDocked didn't apply",
        ])
        # The display was checked, then the human warned, before the lid closed.
        commands = host.commands_run
        self.assertLess(commands.index(sleep.MONITORS), commands.index(WATCH))
        self.assertLess(prompts(host).index(CONNECT_PROMPT), prompts(host).index(CLAMSHELL_PROMPT))

    def test_after_the_recorded_suspend_wi_fi_comes_back_and_thunderbolt_networking_doesnt(self):
        host, _ = self.clamshell(recorded_failure())

        wifi = check(host, sleep.WIFI_AFTER)
        self.assertEqual((wifi["status"], wifi["classification"]["feature"]), ("pass", "wifi"))
        self.assertEqual(wifi["evidence"], [
            "before sleeping: wlan0 connected with an IPv4 address",
            "after waking up: an IPv4 address again 5.0 s after the Mac woke up",
        ])
        thunderbolt = check(host, sleep.THUNDERBOLT_AFTER)
        self.assertEqual((thunderbolt["status"], thunderbolt["classification"]["feature"]), ("fail", "thunderbolt"))
        self.assertEqual(thunderbolt["evidence"], [
            "before sleeping: 1 Thunderbolt/USB4 device(s), thunderbolt0 up (Thunderbolt networking)",
            "after waking up: thunderbolt0 still down 30.0 s after the Mac woke up",
            "Thunderbolt/USB4 devices: 1 before, 0 30.0 s after waking up",
            "the kernel logged 3 Thunderbolt link error(s) or timeout(s) at wake-up",
        ])
        # Polled once a second (the first poll 1 s after the wake-up) until 30 s had passed, and no longer.
        self.assertEqual(host.commands_run.count(sleep.LINKS), 1 + 30)
        self.assertEqual(host.commands_run.count(sleep.SLEEP_ONE), 29)

    def test_a_good_clamshell_stays_awake_on_the_external_display(self):
        host, result = self.clamshell(clamshell_only())

        self.assertEqual((result["status"], result["classification"]["outcome"]), ("pass", "works"))
        self.assertEqual(result["evidence"], [
            "before: eDP-1 on, HDMI-A-1 on",
            "logind: Docked=yes, HandleLidSwitch=suspend, HandleLidSwitchDocked=ignore",
            "lid closed for 11.0 s: the Mac stayed awake",
            "while the lid was closed: eDP-1 off, HDMI-A-1 on",
            "after the lid opened: eDP-1 on, HDMI-A-1 on",
        ])
        # It didn't sleep, so there's no resume to check Wi-Fi and Thunderbolt after.
        self.assertEqual(check(host, sleep.WIFI_AFTER)["status"], "skip")
        self.assertEqual(host.commands_run.count(sleep.LINKS), 1)

    def test_screens_in_the_wrong_state_fail(self):
        at = CLAMSHELL_AT + 0.5
        for events, problem in (
            ([(0, "monitors eDP-1=on HDMI-A-1=on"), (3.0, "closed"), (14.0, "open")], "the built-in screen stayed on with the lid closed"),
            ([(0, "monitors eDP-1=on HDMI-A-1=on"), (3.0, "closed"), (3.5, "monitors eDP-1=off HDMI-A-1=off"), (14.0, "open"),
              (14.5, "monitors eDP-1=on HDMI-A-1=on")], "no external display was on with the lid closed"),
            ([(0, "monitors eDP-1=on HDMI-A-1=on"), (3.0, "closed"), (3.5, "monitors eDP-1=off HDMI-A-1=on"), (14.0, "open")],
             "the built-in screen didn't come back within 3 s of the lid opening"),
        ):
            with self.subTest(problem=problem):
                _, result = self.clamshell(clamshell_only(lid_watches=[watch(at, *events)]))

                self.assertEqual(result["status"], "fail")
                self.assertEqual(result["evidence"][-1], problem)

    def test_without_an_external_display_the_lid_isnt_asked_for(self):
        for answers, state, why in (
            (("n", "n"), clamshell_only(), "skipped: no external display was connected"),
            (("n", EOF), clamshell_only(), "skipped: no external display was connected"),
            (("n", "y"), clamshell_only(monitors="eDP-1=on "), "skipped: Hyprland shows no external display on"),
            (("n", "y"), clamshell_only(monitors="eDP-1=on HDMI-A-1=off "), "skipped: Hyprland shows no external display on"),
            (("n", "y", "n"), clamshell_only(), "skipped: you chose not to close the lid"),
        ):
            with self.subTest(why=why, answers=answers):
                host, result = self.clamshell(state, answers)

                self.assertEqual((result["status"], result["evidence"][-1]), ("skip", why))
                self.assertEqual(watches(host), 0)

    def test_screens_read_in_the_same_poll_as_the_lid_opening_count_as_after(self):
        # The watch reads the lid, then the monitors: when both change in one poll they share its time.
        same = watch(CLAMSHELL_AT + 0.5, (0, "monitors eDP-1=on HDMI-A-1=on"), (3.0, "closed"), (3.0, "monitors eDP-1=on HDMI-A-1=on"),
                     (3.5, "monitors eDP-1=off HDMI-A-1=on"), (14.0, "open"), (14.0, "monitors eDP-1=on HDMI-A-1=on"))
        _, result = self.clamshell(clamshell_only(lid_watches=[same]))

        self.assertEqual(result["status"], "pass")
        self.assertIn("while the lid was closed: eDP-1 off, HDMI-A-1 on", result["evidence"])
        self.assertIn("after the lid opened: eDP-1 on, HDMI-A-1 on", result["evidence"])

    def test_a_system_log_without_lid_events_cant_show_a_suspend(self):
        # Only the user's own journal is readable: no logind lines at all, so staying awake proves nothing.
        _, result = self.clamshell(clamshell_only(journal=journal(lines=40)))

        self.assertEqual(result["status"], "skip")
        self.assertIn("the system log shows no lid events", result["evidence"][-1])
        stayed = watch(SUSPEND_AT + 0.5, (0, "monitors eDP-1=on"), (3.0, "closed"), (13.0, "open"))
        suspend = check(sleep_run(["y", "n"], suspend_only(lid_watches=[stayed], journal=journal(lines=40))), sleep.LID_SUSPEND)
        self.assertEqual(suspend["status"], "skip")

    def test_a_lid_opened_straight_away_says_nothing(self):
        quick = watch(CLAMSHELL_AT + 0.5, (0, "monitors eDP-1=on HDMI-A-1=on"), (3.0, "closed"), (4.0, "open"))
        _, result = self.clamshell(clamshell_only(lid_watches=[quick]))

        self.assertEqual(result["status"], "skip")
        self.assertIn("the lid was open again after 1.0 s", result["evidence"][-1])

    def test_reference_runs_dont_ask_for_the_clamshell(self):
        from tests.test_core_checks import reference

        host = sleep_run(["y"], suspend_only(), rec=live_recording(base=reference(json.loads(json.dumps(live_recording())))))

        self.assertNotIn(CONNECT_PROMPT, prompts(host))
        self.assertEqual(check(host, sleep.CLAMSHELL)["status"], "skip")
        self.assertEqual(check(host, sleep.LID_SUSPEND)["status"], "pass")


# -- at the terminal: the lid wait's countdown, and the wait after waking up ---------------------

def at_the_terminal(answers, state: MacState) -> LiveMac:
    """The Sleep section at an Omarchy terminal: gum confirms (0 yes, 1 no) after the disclaimer and the picker."""
    host = LiveMac(omarchy_desktop(live_recording()), state=state, terminal_size=TERMINAL,
                   answers=[ENTER, CommandResult(0, "Sleep\n", ""), *(CommandResult(code, "", "") for code in answers), ENDED])
    main(ARGS, host, sections=(SECTIONS["sleep"],))
    return host


# The M2 Max at its desk, 2026-09-27: Wi-Fi back 2.6 s after waking up, Thunderbolt networking never.
M2_BEFORE = links(SUSPEND_AT, tbnet=True, tbdevices=1)
M2_AFTER = [links(SUSPEND_AT + 17.0 + i, wifi=0 if i < 2 else 1, tbnet=False, tbdevices=1) for i in range(40)]


class TerminalTest(unittest.TestCase):
    def test_after_waking_up_the_wait_is_said_and_the_feed_isnt_the_same_poll_over_and_over(self):
        """The M2 Max, 2026-09-27: the feed redrew the same poll every second for 30 s, which looked like a loop."""
        host = at_the_terminal([0, 1], suspend_only(links=[M2_BEFORE, *M2_AFTER]))

        self.assertEqual(check(host, sleep.THUNDERBOLT_AFTER)["status"], "fail")
        self.assertEqual(check(host, sleep.WIFI_AFTER)["status"], "pass")
        # Said once, before the wait: how long, and what it waits for.
        said = sleep.RECOVERY_WAIT.format(what="wlan0 with an address, thunderbolt0 (Thunderbolt networking), 1 Thunderbolt/USB4 device(s)")
        text = " ".join(re.sub(r"\033\[[0-9;?]*[A-Za-z]", "", host.output).split())  # wrapped at the terminal
        self.assertIn(said, text)
        self.assertEqual(text.count("The Mac woke up. Waiting up to"), 1)
        # Bounded: polled until RECOVERY_SECONDS after the wake-up, and no more.
        polls = host.commands_run.count(sleep.LINKS) - 1
        self.assertEqual(polls, sleep.RECOVERY_SECONDS + 1)
        # The feed shows no poll at all, only what changed: first nothing back, then Wi-Fi.
        frames = [e[1] for e in host.transcript if e[0] == "show" and "  → " in e[1]]
        feed = "".join(frames)
        self.assertNotIn("$ sleep 1", feed)
        self.assertLessEqual(frames[-1].count("$ sh -c echo \"time"), 1)  # at most the links read before the lid closed
        said = " ".join(re.sub(r"\033\[[0-9;?]*[A-Za-z]", "", frames[-1]).replace("→", " ").split())
        self.assertIn("1 s after waking up: wlan0 no address, thunderbolt0 down, 1 of 1 Thunderbolt/USB4 device(s)", said)
        self.assertIn("3 s after waking up: wlan0 connected, thunderbolt0 down", said)

    def test_the_lid_wait_runs_on_the_terminal_with_a_countdown_and_is_generous(self):
        late = watch(SUSPEND_AT + 0.5, (0, "monitors eDP-1=on"), (40.0, "closed"), (53.0, "open"))
        journal_late = journal(("lid-closed", SUSPEND_AT + 40.6), ("suspend-entry", SUSPEND_AT + 41.3, "s2idle"),
                               ("suspend-exit", SUSPEND_AT + 53.4), ("lid-opened", SUSPEND_AT + 53.5))
        host = at_the_terminal([0, 1], suspend_only(lid_watches=[late], journal=journal_late))

        self.assertGreaterEqual(sleep.CLOSE_SECONDS, 60)
        self.assertEqual(check(host, sleep.LID_SUSPEND)["status"], "pass")  # closed after 40 s: still in time
        watches_ = [argv for kind, argv, _ in (e for e in host.transcript if e[0] == "tty") if argv[:3] == WATCH[:3]]
        self.assertEqual(len(watches_), 1)
        self.assertEqual(watches_[0][4:8], [str(sleep.CLOSE_SECONDS), str(sleep.CLOSED_SECONDS), str(sleep.AFTER_OPEN_SECONDS), "1"])
        self.assertEqual(watches_[0][8].strip(), "Sleep")

    def test_a_key_while_the_lid_is_awaited_skips_the_step(self):
        skipped = watch(SUSPEND_AT + 0.5, (0, "monitors eDP-1=on"), end="skipped")
        host = at_the_terminal([0, 1], suspend_only(lid_watches=[skipped], journal=journal()))

        self.assertEqual(check(host, sleep.LID_SUSPEND)["evidence"], ["before: eDP-1 on", f"skipped: {sleep.LID_SKIPPED}"])
        self.assertEqual(check(host, sleep.WIFI_AFTER)["status"], "skip")

    def test_the_watch_script_counts_down_on_stderr_and_ends_on_a_key(self):
        """The countdown and the key, in the watch's own shell (bash, as on Arch), with logind and Hyprland stubbed."""
        import os, shutil, subprocess, tempfile
        def fractional(bash):
            return bash and subprocess.run([bash, "-c", "read -t 0.1 x"], input="", capture_output=True, text=True).stderr == ""
        bash = next((b for b in (shutil.which("bash"), "/opt/homebrew/bin/bash", "/usr/bin/bash") if b and os.path.exists(b) and fractional(b)), None)
        if bash is None:
            self.skipTest("needs a bash whose read takes fractional timeouts (bash 4+, as on Arch)")
        with tempfile.TemporaryDirectory() as stubs:
            for name, body in (("busctl", "echo 'b false'"), ("hyprctl", "true"), ("sleep", "true")):
                with open(os.path.join(stubs, name), "w") as f:
                    f.write(f"#!/bin/sh\n{body}\n")
                os.chmod(os.path.join(stubs, name), 0o755)
            env = {**os.environ, "PATH": stubs + os.pathsep + os.environ["PATH"]}
            argv = sleep.lid_watch_argv(close=2, tty=True, label="  Sleep")
            keyed = subprocess.run([bash, "--posix", *argv[1:]], input="x", capture_output=True, text=True, env=env, timeout=20)
            waited = subprocess.run([bash, "--posix", *argv[1:]], input="", capture_output=True, text=True, env=env, timeout=20)
        self.assertIn("skipped", keyed.stdout.split()[-2:])
        self.assertIn("  Sleep: close the lid now, 2 s left (any key skips)", keyed.stderr)
        self.assertEqual(waited.stdout.split()[-2], "timeout")
        self.assertIn("1 s left", waited.stderr)
        self.assertTrue(waited.stderr.endswith("\033[2K"))  # the countdown's line is cleared at the end


# -- Wi-Fi and Thunderbolt after the resume --------------------------------------------------

class AfterResumeTest(unittest.TestCase):
    def test_wi_fi_that_never_gets_its_address_back_fails(self):
        never = [links(SUSPEND_AT + 17.4 + i, wifi=0) for i in range(40)]
        host = sleep_run(["y", "n"], suspend_only(links=[BEFORE_SUSPEND, *never]))

        result = check(host, sleep.WIFI_AFTER)
        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["evidence"][-1], "after waking up: no IPv4 address 30.0 s after the Mac woke up (wlan0 down with 0 IPv4 address(es))")

    def test_what_wasnt_up_before_sleeping_is_skipped(self):
        host = sleep_run(["y", "n"], suspend_only(links=[links(SUSPEND_AT, wifi=None), links(SUSPEND_AT + 18, wifi=None)]))

        self.assertEqual(check(host, sleep.WIFI_AFTER)["evidence"], ["skipped: Wi-Fi wasn't connected with an address before the Mac went to sleep"])
        self.assertEqual(check(host, sleep.THUNDERBOLT_AFTER)["evidence"], ["skipped: nothing was connected over Thunderbolt or USB4 before the Mac went to sleep"])

    def test_thunderbolt_that_comes_back_passes(self):
        before = links(SUSPEND_AT, tbnet=True, tbdevices=1)
        back = [links(SUSPEND_AT + 17.4, tbnet=False, tbdevices=0), links(SUSPEND_AT + 18.4, tbnet=True, tbdevices=1)]
        host = sleep_run(["y", "n"], suspend_only(links=[before, *back]))

        result = check(host, sleep.THUNDERBOLT_AFTER)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["evidence"][-1], "after waking up: all back 2.0 s after the Mac woke up")

    def test_only_the_first_resume_is_checked(self):
        # The suspend step woke up with everything back; the recorded clamshell failure then suspends again.
        state = MacState(lid_watches=[GOOD_SUSPEND_WATCH, FAILED_CLAMSHELL_WATCH],
                         journal=GOOD_SUSPEND_JOURNAL.replace("lines 120\n", "") + FAILED_CLAMSHELL_JOURNAL,
                         links=[BEFORE_SUSPEND, AWAKE_AGAIN, BEFORE_FAILED_CLAMSHELL, *FAILED_AFTER],
                         monitors=USB_C_DISPLAY, logind=[LOGIND_UNDOCKED, LOGIND_UNDOCKED])
        host = sleep_run(["y", "y", "y"], state)

        self.assertEqual(check(host, sleep.LID_SUSPEND)["status"], "pass")
        self.assertEqual(check(host, sleep.CLAMSHELL)["status"], "fail")
        self.assertEqual(check(host, sleep.THUNDERBOLT_AFTER)["status"], "skip")  # nothing on Thunderbolt at the first
        self.assertEqual(host.commands_run.count(sleep.SLEEP_ONE), 0)


# -- surviving the suspend: the checkpoint --------------------------------------------------

class Stopped(LiveMac):
    """The run is stopped (the terminal closed) while the lid step watches the lid."""

    def run(self, argv):
        if list(argv) == WATCH:
            raise KeyboardInterrupt
        return super().run(argv)


class CheckpointTest(unittest.TestCase):
    def stopped(self, answers, state: MacState) -> str:
        first = Stopped(live_recording(), state=state, answers=[ENTER, *answers])
        self.assertEqual(main(ARGS, first, sections=(SECTIONS["sleep"],)), 130)
        self.assertIn("Run omarchy-m-test again to resume", first.output)
        saved = json.loads(first.written[CHECKPOINT])
        self.assertIn("step", saved["shared"]["progress"]["sleep"])
        return first.written[CHECKPOINT]

    def resumed(self, checkpoint: str, answers, state: MacState) -> LiveMac:
        second = LiveMac(live_recording(checkpoint=checkpoint), state=state, answers=[ENTER, ENTER, *answers, ENDED])
        self.assertEqual(main(ARGS, second, sections=(SECTIONS["sleep"],)), 0)
        return second

    def test_a_run_stopped_while_the_lid_was_closed_resumes_and_reads_the_system_log(self):
        checkpoint = self.stopped(["y"], suspend_only())

        second = self.resumed(checkpoint, ["n"], suspend_only(links=[AWAKE_AGAIN], lid_watches=[]))

        self.assertIn("Resume where it stopped? [Y/n] ", prompts(second))
        self.assertIn(sleep.RECOVERED_NOTE, second.output)
        self.assertNotIn(SUSPEND_PROMPT, prompts(second))  # the lid isn't asked for again
        self.assertEqual(watches(second), 0)
        result = check(second, sleep.LID_SUSPEND)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["evidence"], [
            "lid closed: the Mac went to sleep 0.70 s later (s2idle)",
            "woke up after 12.1 s asleep, when the lid opened",
            "read from the system log: the run had stopped while the lid was closed",
        ])
        # Wi-Fi is judged from the links before the lid closed (in the checkpoint) and now.
        self.assertEqual(check(second, sleep.WIFI_AFTER)["status"], "pass")
        self.assertIn(CONNECT_PROMPT, prompts(second))  # and the run carries on with the clamshell step
        self.assertNotIn(CHECKPOINT, second.written)  # the report was written: the checkpoint is gone

    def test_a_mac_that_had_to_be_started_again_fails(self):
        checkpoint = self.stopped(["y"], suspend_only())

        second = self.resumed(checkpoint, ["n"], suspend_only(boot_id="5a1f0c3e-9d2b-4e87-b6a4-3c8e1f7d2b90"))

        result = check(second, sleep.LID_SUSPEND)
        self.assertEqual((result["status"], result["classification"]["outcome"]), ("fail", "fails"))
        self.assertIn("the Mac was started again since: it didn't come back from sleep", result["evidence"][0])
        self.assertEqual(check(second, sleep.WIFI_AFTER)["status"], "skip")

    def test_a_run_stopped_in_the_clamshell_step_keeps_the_suspend_steps_result(self):
        class StoppedSecond(LiveMac):
            def run(self, argv):
                if list(argv) == WATCH and self.state.lid_watches == [GOOD_CLAMSHELL_WATCH] and getattr(self, "seen", False):
                    raise KeyboardInterrupt
                if list(argv) == WATCH:
                    self.seen = True
                return super().run(argv)

        first = StoppedSecond(live_recording(), answers=[ENTER, "y", "y", "y"])
        self.assertEqual(main(ARGS, first, sections=(SECTIONS["sleep"],)), 130)
        saved = json.loads(first.written[CHECKPOINT])["shared"]["progress"]["sleep"]
        self.assertEqual((saved["step"]["name"], saved["results"][sleep.LID_SUSPEND]["status"]), ("clamshell", "pass"))

        second = self.resumed(first.written[CHECKPOINT], [], clamshell_only(journal=GOOD_CLAMSHELL_JOURNAL))

        self.assertNotIn(SUSPEND_PROMPT, prompts(second))
        self.assertNotIn(CONNECT_PROMPT, prompts(second))
        self.assertEqual(check(second, sleep.LID_SUSPEND)["status"], "pass")
        clamshell = check(second, sleep.CLAMSHELL)
        self.assertEqual(clamshell["status"], "skip")
        self.assertIn("the run stopped before the displays could be seen with the lid closed", clamshell["evidence"][-1])

    def test_a_stopped_clamshell_that_slept_fails_from_the_log(self):
        first = Stopped(live_recording(), state=recorded_failure(), answers=[ENTER, "n", "y", "y"])
        self.assertEqual(main(ARGS, first, sections=(SECTIONS["sleep"],)), 130)

        second = self.resumed(first.written[CHECKPOINT], [], recorded_failure(links=[FAILED_AFTER[-1]]))

        clamshell = check(second, sleep.CLAMSHELL)
        self.assertEqual(clamshell["status"], "fail")
        self.assertIn("lid closed: the Mac went to sleep 0.74 s later (s2idle), with USB-2 on", clamshell["evidence"])
        self.assertEqual(check(second, sleep.THUNDERBOLT_AFTER)["status"], "fail")

    def test_a_checkpoint_with_a_step_it_cant_read_starts_the_section_over(self):
        checkpoint = json.loads(self.stopped(["y"], suspend_only()))
        checkpoint["shared"]["progress"]["sleep"] = {"step": {"since": "soon"}, "results": ["garbage"]}

        second = self.resumed(json.dumps(checkpoint), ["y", "n"], suspend_only())

        self.assertIn(SUSPEND_PROMPT, prompts(second))
        self.assertEqual(check(second, sleep.LID_SUSPEND)["status"], "pass")


# -- never over SSH, and the golden runs -----------------------------------------------------

class PresenceTest(unittest.TestCase):
    def test_never_over_ssh_or_without_a_local_seat(self):
        for rec, state, why in (
            (live_recording({"SSH_CONNECTION": "192.168.0.20 51514 192.168.0.106 22"}), None, "running over SSH"),
            (live_recording(), MacState(session={"Remote": "no", "Seat": "", "Active": "yes"}), "no local desktop session"),
        ):
            with self.subTest(why=why):
                host = run("sleep", [ENDED], rec=rec, state=state)

                for check_id in sleep.CHECK_IDS:
                    self.assertIn(why, check(host, check_id)["evidence"][0])
                self.assertNotIn(SUSPEND_PROMPT, prompts(host))
                self.assertEqual(host.commands_run.count(sleep.LINKS), 0)

    def test_the_recorded_runs_over_ssh_skip_the_sleep_section_with_the_reason(self):
        from tests.test_audio_display import golden

        for name in ("m2-max-image2", "m1-pro-mx-mac", "m1-pro-converged", "m2-max-converged"):
            with self.subTest(name=name):
                checks = golden(name)
                for check_id in sleep.CHECK_IDS:
                    self.assertEqual(checks[check_id]["evidence"], ["skipped: running over SSH, where it could cut the connection"])


class PrivacyTest(unittest.TestCase):
    def test_only_connector_and_interface_names_reach_the_report(self):
        host = sleep_run(["n", "y", "y"], recorded_failure())

        text = json.dumps([check(host, check_id) for check_id in sleep.CHECK_IDS])
        for word in ("wlan0", "thunderbolt0", "USB-2", "eDP-1"):
            self.assertIn(word, text)
        self.assertNotIn(copy.deepcopy(live_recording())["env"]["HOME"], text)
        self.assertNotIn("<ssid>", text)


if __name__ == "__main__":
    unittest.main()
