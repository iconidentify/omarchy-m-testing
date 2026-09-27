"""Seam A: the Power section, with scripted answers: the charge limit, omarchy-mac's saved limit, idle power, drain asleep.

The whole CLI runs against the recorded M2 Max (image 2, with omarchy-mac's
charge limit command, rule and helper), only the Power section.
tests/live_mac.py models the SMC's thresholds, the saved file (with
asahi-scripts' path unit saving every change to it, as image 2 showed:
62-battery-set80.txt), the idle samples, the battery readings and the lid.
"""

from __future__ import annotations

import json
import unittest

from omarchy_m_test import power, sleep
from omarchy_m_test.app import main
from omarchy_m_test.recording import ENDED
from omarchy_m_test.safety import refusal
from omarchy_m_test.host import CommandResult
from tests.desktop import CHECKPOINT, TERMINAL, omarchy_desktop, recording
from tests.live_mac import (
    AFTER_DRAIN, BEFORE_DRAIN, DRAIN_AT, GOOD_DRAIN_JOURNAL, GOOD_DRAIN_WATCH, LiveMac, MacState, journal, live_recording,
    reading, samples,
)
from tests.test_audio_display import SECTIONS, run
from tests.test_interactive import ARGS, ENTER, check, prompts

SAVED_80 = f"{power.SAVED_KEY}=80\n"
UNPLUG = power.unplug_argv(power.SMC_BATTERY)
DRAIN_PROMPT = power.DRAIN_QUESTION + " [y/N] "
WATCH = power.drain_watch_argv()


def power_run(answers=(), state: MacState | None = None, **kwargs) -> LiveMac:
    return run("power", [*answers, ENDED], state=state, **kwargs)


def on_battery(**state) -> MacState:
    return MacState(**{"battery_status": "Discharging", **state})


def drain(**state) -> MacState:
    return on_battery(**{"lid_watches": [GOOD_DRAIN_WATCH], "journal": GOOD_DRAIN_JOURNAL, **state})


def root_commands(host: LiveMac) -> list[list[str]]:
    return [argv for argv in host.commands_run if argv[:2] == ["sudo", "-n"] and argv != ["sudo", "-n", "true"]]


# -- the charge limit -------------------------------------------------------------------------

class ChargeLimitTest(unittest.TestCase):
    def test_the_limit_is_set_cleared_and_put_back_as_it_was(self):
        host = power_run()

        kernel = check(host, power.CHARGE_LIMIT)
        self.assertEqual((kernel["status"], kernel["classification"]["outcome"]), ("pass", "works"))
        self.assertEqual((kernel["classification"]["feature"], kernel["classification"]["layer"]), ("battery-info", "asahi"))
        self.assertEqual(kernel["evidence"], [
            "charge limit before: 100% (charging restarts at 100%)",
            "set 80%: the SMC reads back 80% (charging restarts at 75%)",
            "cleared to 100%: the SMC reads back 100% (charging restarts at 100%)",
            "put back to 100% afterwards",
        ])
        # sysfs 80 and 100, omarchy-mac's command 80 and 100, then the original limit and saved file (none) back.
        self.assertEqual(root_commands(host), [
            power.set_argv(80), power.set_argv(100), power.command_argv(80), power.command_argv(100), power.restore_argv(100, None),
        ])
        self.assertEqual((host.state.charge_limit, host.state.saved_limit), (100, None))
        self.assertNotIn("Couldn't undo", host.output)

    def test_omarchy_macs_command_saves_80_for_its_udev_rule_and_100_clears_it(self):
        host = power_run()

        kept = check(host, power.CHARGE_LIMIT_KEPT)
        self.assertEqual((kept["status"], kept["classification"]["outcome"]), ("pass", "works"))
        self.assertEqual((kept["classification"]["feature"], kept["classification"]["layer"]), ("battery-charge-limit", "omarchy"))
        self.assertEqual(kept["evidence"], [
            "`omarchy-battery-charge-limit` shows 100%, as the SMC has",
            "omarchy-mac's udev rule and helper that restore a saved limit at boot are installed",
            "nothing saved in /etc/udev/macsmc-battery.conf",
            "`omarchy battery charge limit 80`: the SMC reads back 80% (charging restarts at 75%), 80% saved for the next boot",
            "`omarchy battery charge limit 100`: the SMC reads back 100% (charging restarts at 100%)",
            "the saved limit put back as it was (no /etc/udev/macsmc-battery.conf)",
        ])

    def test_a_user_set_80_limit_and_its_saved_file_are_put_back(self):
        host = power_run(state=MacState(charge_limit=80, saved_limit=SAVED_80))

        self.assertEqual(root_commands(host)[-1], power.restore_argv(80, SAVED_80))
        self.assertEqual((host.state.charge_limit, host.state.saved_limit), (80, SAVED_80))
        self.assertEqual(check(host, power.CHARGE_LIMIT)["evidence"][-1], "put back to 80% afterwards")
        self.assertIn("saved for the next boot: 80%", check(host, power.CHARGE_LIMIT_KEPT)["evidence"])

    def test_a_limit_the_smc_doesnt_take_fails_and_is_still_put_back(self):
        state = MacState(limit_sticks=False, charge_limit=100)
        host = power_run(state=state)

        kernel = check(host, power.CHARGE_LIMIT)
        self.assertEqual((kernel["status"], kernel["classification"]["outcome"]), ("fail", "fails"))
        self.assertIn("80% didn't stick: expected 80% (charging restarts at 75%)", kernel["evidence"])
        self.assertEqual(check(host, power.CHARGE_LIMIT_KEPT)["status"], "fail")
        self.assertEqual(host.state.charge_limit, 100)

    def test_a_saved_80_the_command_didnt_write_fails_the_kept_check(self):
        class NoSave(LiveMac):
            def _answer(self, argv):
                answer = super()._answer(argv)
                if argv[:3] == ["sudo", "-n", power.COMMAND]:
                    self.state.saved_limit = None
                return answer

        host = power_run(cls=NoSave)

        kept = check(host, power.CHARGE_LIMIT_KEPT)
        self.assertEqual(kept["status"], "fail")
        self.assertIn("80% wasn't saved in /etc/udev/macsmc-battery.conf, so the next boot wouldn't keep it", kept["evidence"])
        self.assertEqual(check(host, power.CHARGE_LIMIT)["status"], "pass")

    def test_without_sudo_nothing_is_changed_and_both_are_skipped(self):
        host = power_run(state=MacState(sudo_cached=False))

        self.assertEqual(root_commands(host), [])
        kernel, kept = check(host, power.CHARGE_LIMIT), check(host, power.CHARGE_LIMIT_KEPT)
        self.assertEqual((kernel["status"], kernel["classification"]["outcome"]), ("skip", "not-tested"))
        self.assertEqual(kernel["evidence"][-1], "skipped: setting the charge limit needs sudo, and it wasn't given")
        self.assertEqual(kept["status"], "skip")
        self.assertIn("`omarchy-battery-charge-limit` shows 100%, as the SMC has", kept["evidence"])

    def test_without_omarchy_macs_command_the_kept_check_fails_and_the_kernel_one_still_runs(self):
        rec = live_recording(base=recording("m1-pro-mx-mac"))
        host = power_run(rec=rec)

        kept = check(host, power.CHARGE_LIMIT_KEPT)
        self.assertEqual(kept["status"], "fail")
        self.assertIn("omarchy-battery-charge-limit isn't installed (omarchy-mac's `omarchy battery charge limit`)", kept["evidence"])
        self.assertIn("nothing of omarchy-mac's restores a saved limit at boot "
                      "(/usr/lib/udev/rules.d/94-omarchy-mac-battery-charge-limit.rules, "
                      "/usr/lib/omarchy-mac/battery-charge-limit-restore missing)", kept["evidence"])
        self.assertEqual(check(host, power.CHARGE_LIMIT)["status"], "pass")
        self.assertNotIn(power.command_argv(80), host.commands_run)

    def test_without_sudo_a_missing_command_still_fails_the_kept_check(self):
        host = power_run(rec=live_recording(base=recording("m1-pro-mx-mac")), state=MacState(sudo_cached=False))

        self.assertEqual(root_commands(host), [])
        self.assertEqual(check(host, power.CHARGE_LIMIT)["status"], "skip")
        self.assertEqual(check(host, power.CHARGE_LIMIT_KEPT)["status"], "fail")

    def test_ctrl_c_mid_change_puts_the_limit_and_the_saved_file_back(self):
        class Interrupted(LiveMac):
            def run(self, argv):
                if list(argv) == power.command_argv(80):
                    super().run(argv)  # it's set and saved, then Ctrl-C
                    raise KeyboardInterrupt
                return super().run(argv)

        state = MacState(charge_limit=100, saved_limit=None)
        host = Interrupted(live_recording(), state=state, answers=[ENTER, ENDED])

        self.assertEqual(main(ARGS, host, sections=(SECTIONS["power"],)), 130)
        self.assertEqual(host.commands_run[-1], power.restore_argv(100, None))
        self.assertEqual((host.state.charge_limit, host.state.saved_limit), (100, None))

    def test_every_command_passes_the_guard_and_writes_only_the_battery_and_its_saved_file(self):
        for argv in (power.set_argv(80), power.restore_argv(80, SAVED_80), power.restore_argv(100, None), power.command_argv(80)):
            self.assertIsNone(refusal(argv), argv)
        self.assertIn(f"> {power.END}", power.RESTORE_SCRIPT)
        self.assertIn(f"> {power.SAVED}", power.RESTORE_SCRIPT)


# -- idle power ---------------------------------------------------------------------------------

class IdleDrawTest(unittest.TestCase):
    def test_on_battery_30_seconds_of_power_now_are_averaged(self):
        host = power_run(state=on_battery())

        result = check(host, power.IDLE_DRAW)
        self.assertEqual((result["status"], result["classification"]["outcome"]), ("pass", "works"))
        self.assertEqual(result["evidence"], [
            "idle on battery for 30 s: 6.2 W average (lowest 5.8 W, highest 7.2 W), from power_now",
        ])
        self.assertIn(power.idle_argv(power.SMC_BATTERY), host.commands_run)
        self.assertNotIn(UNPLUG, host.commands_run)
        self.assertNotIn(power.UNPLUG, host.output)
        self.assertLess(host.output.index(power.MEASURING), len(host.output))

    def test_without_power_now_current_times_voltage_is_used(self):
        host = power_run(state=on_battery(idle=samples(*[6.0] * 30, power_now=False)))

        self.assertEqual(check(host, power.IDLE_DRAW)["evidence"], [
            "idle on battery for 30 s: 6.0 W average (lowest 6.0 W, highest 6.0 W), from current_now x voltage_now",
        ])

    def test_a_busy_idle_mac_passes_and_says_so(self):
        host = power_run(state=on_battery(idle=samples(*[18.0] * 30)))

        result = check(host, power.IDLE_DRAW)
        self.assertEqual(result["status"], "pass")
        self.assertIn("something may be keeping it busy", result["evidence"][-1])

    def test_a_battery_that_reports_no_draw_while_discharging_fails(self):
        host = power_run(state=on_battery(idle="sample Discharging 0 0 12600000\n" * 30))

        result = check(host, power.IDLE_DRAW)
        self.assertEqual((result["status"], result["classification"]["outcome"]), ("fail", "fails"))

    def test_on_ac_power_at_the_mac_the_charger_is_asked_for_first_thing_and_waited_for(self):
        host = power_run(state=MacState(battery_status="Full", unplug="Discharging"))

        # Said up front, before the section changes anything, and waited for rather than asked about.
        commands = host.commands_run
        self.assertLess(commands.index(UNPLUG), commands.index(power.set_argv(80)))
        self.assertEqual(host.output.count(power.UNPLUG), 1)
        self.assertEqual(check(host, power.IDLE_DRAW)["status"], "pass")
        self.assertIn(DRAIN_PROMPT, prompts(host))
        self.assertIn(power.PLUG_BACK, host.output)

    def test_a_charger_left_in_skips_both_and_says_so_without_offering_the_drain(self):
        """The M2 Max, 2026-09-27: on the charger, the drain said about ten minutes and the report came at once."""
        host = power_run(state=MacState(battery_status="Charging"))

        why = f"skipped: the charger stayed plugged in for {power.UNPLUG_SECONDS} s (battery Charging)"
        self.assertEqual(check(host, power.IDLE_DRAW)["evidence"], [why])
        self.assertEqual(check(host, power.SLEEP_DRAIN)["evidence"], [why])
        self.assertFalse(any(argv[:3] == ["sh", "-c", power.IDLE_SCRIPT] for argv in host.commands_run))
        self.assertNotIn(DRAIN_PROMPT, prompts(host))
        self.assertNotIn(power.DRAIN_WARNING, host.output)
        self.assertIn(power.STILL_PLUGGED, host.output)
        self.assertEqual(host.commands_run.count(UNPLUG), 1)

    def test_at_the_terminal_the_wait_counts_down_and_a_key_skips_it(self):
        host = LiveMac(omarchy_desktop(live_recording()), state=MacState(battery_status="Full", key_pressed=True),
                       answers=[ENTER, CommandResult(0, "Power\n", ""), ENDED], terminal_size=TERMINAL)
        self.assertEqual(main(ARGS, host, sections=(SECTIONS["power"],)), 0)

        waits = [argv for kind, argv, _ in (e for e in host.transcript if e[0] == "tty") if argv[:3] == UNPLUG[:3]]
        self.assertEqual(len(waits), 1)
        self.assertEqual(waits[0][6], "1")  # the countdown and the key, on the terminal
        self.assertTrue(waits[0][7].endswith("Power"))
        self.assertEqual(check(host, power.IDLE_DRAW)["evidence"], ["skipped: you chose not to unplug the charger (battery Full)"])

    def test_the_charger_plugged_back_in_during_the_measurement_skips_it(self):
        host = power_run(state=MacState(battery_status="Full", unplug="Discharging", idle=samples(*[6.0] * 30, status="Charging")))

        self.assertEqual(check(host, power.IDLE_DRAW)["evidence"], ["skipped: the Mac wasn't on battery for the measurement (battery Charging)"])

    def test_over_ssh_on_ac_power_it_is_skipped_without_asking(self):
        host = power_run(rec=live_recording(env={"SSH_CONNECTION": "10.0.0.2 50000 10.0.0.1 22"}), state=MacState(battery_status="Full"))

        result = check(host, power.IDLE_DRAW)
        self.assertEqual(result["status"], "skip")
        self.assertIn("the Mac is on AC power (battery Full)", result["evidence"][0])
        self.assertNotIn(UNPLUG, host.commands_run)
        self.assertNotIn(power.UNPLUG, host.output)
        self.assertNotIn(DRAIN_PROMPT, prompts(host))
        self.assertEqual(check(host, power.SLEEP_DRAIN)["evidence"], ["skipped: running over SSH, where it could cut the connection"])


# -- drain while asleep ----------------------------------------------------------------------

class SleepDrainTest(unittest.TestCase):
    def test_ten_minutes_asleep_give_the_drain_in_watts_and_percent_an_hour(self):
        host = power_run(["y"], state=drain())

        result = check(host, power.SLEEP_DRAIN)
        self.assertEqual((result["status"], result["classification"]["outcome"]), ("pass", "works"))
        self.assertEqual((result["classification"]["feature"], result["classification"]["layer"]), ("suspend-sleep", "asahi"))
        self.assertEqual(result["evidence"], [
            "asleep for 10.2 min (s2idle), on battery",
            "battery: 77.20 Wh to 76.94 Wh",
            "drain: 1.6% per hour asleep, 1.53 W on average (a full battery would last about 62 h asleep)",
        ])
        # Warned first; the battery read and the step checkpointed before the lid watch; read again after it.
        self.assertLess(host.output.index(f"close the lid (the run waits up to {sleep.CLOSE_SECONDS} s for it)"), host.output.index(DRAIN_PROMPT))
        commands = host.commands_run
        reads = [i for i, argv in enumerate(commands) if argv == power.reading_argv(power.SMC_BATTERY)]
        self.assertEqual(len(reads), 2)
        self.assertLess(reads[0], commands.index(WATCH))
        self.assertLess(commands.index(WATCH), reads[1])
        self.assertIn(sleep.journal_argv(int(DRAIN_AT) - 1), commands)
        self.assertIn(power.PLUG_BACK, host.output)

    def test_a_mac_that_loses_more_than_8_percent_an_hour_asleep_fails(self):
        host = power_run(["y"], state=drain(readings=[BEFORE_DRAIN, reading(DRAIN_AT + 620, 75_700_000)]))

        result = check(host, power.SLEEP_DRAIN)
        self.assertEqual((result["status"], result["classification"]["outcome"]), ("fail", "fails"))
        self.assertIn("drain: 9.3% per hour asleep", result["evidence"][2])
        self.assertEqual(result["evidence"][-1], "more than 8% per hour: the Mac isn't sleeping deeply enough")

    def test_without_energy_the_capacity_is_used(self):
        state = drain(readings=[reading(DRAIN_AT, None, capacity=81), reading(DRAIN_AT + 620, None, capacity=80)])
        host = power_run(["y"], state=state)

        self.assertEqual(check(host, power.SLEEP_DRAIN)["evidence"][1], "battery: 81% to 80%")

    def test_opened_too_soon_it_is_skipped(self):
        at = DRAIN_AT
        state = drain(journal=journal(("lid-closed", at + 3.6), ("suspend-entry", at + 4.3, "s2idle"), ("suspend-exit", at + 64.3)))
        host = power_run(["y"], state=state)

        result = check(host, power.SLEEP_DRAIN)
        self.assertEqual(result["status"], "skip")
        self.assertIn("too short to measure", result["evidence"][-1])

    def test_a_mac_that_didnt_go_to_sleep_is_skipped_for_the_lid_check_to_explain(self):
        host = power_run(["y"], state=drain(journal=journal(("lid-closed", DRAIN_AT + 3.6), ("lid-opened", DRAIN_AT + 30))))

        self.assertEqual(check(host, power.SLEEP_DRAIN)["evidence"], [
            "skipped: the Mac didn't go to sleep with the lid closed (sleep.lid-suspend checks why)",
        ])

    def test_a_charger_plugged_back_in_is_waited_for_again(self):
        readings = [reading(DRAIN_AT - 5, 77_300_000, status="Charging"), BEFORE_DRAIN, AFTER_DRAIN]
        host = power_run(["y"], state=drain(readings=readings, unplug="Discharging"))

        self.assertEqual(check(host, power.SLEEP_DRAIN)["status"], "pass")
        self.assertIn("The charger is plugged in again (battery Charging)", host.output)
        self.assertLess(host.commands_run.index(UNPLUG), host.commands_run.index(WATCH))

    def test_a_charger_that_stays_in_after_yes_skips_it_and_says_so_at_once(self):
        host = power_run(["y"], state=on_battery(readings=[reading(DRAIN_AT, 77_200_000, status="Full")], unplug="Full"))

        why = f"the charger stayed plugged in for {power.UNPLUG_SECONDS} s (battery Full)"
        self.assertEqual(check(host, power.SLEEP_DRAIN)["evidence"], [f"skipped: {why}"])
        self.assertIn(power.DRAIN_SKIPPED.format(why=why), host.output)
        self.assertNotIn(WATCH, host.commands_run)

    def test_a_drain_skipped_after_the_lid_says_why_before_the_report(self):
        at = DRAIN_AT
        state = drain(journal=journal(("lid-closed", at + 3.6), ("suspend-entry", at + 4.3, "s2idle"), ("suspend-exit", at + 64.3)))
        host = power_run(["y"], state=state)

        self.assertIn("Battery drain while asleep: skipped (too short to measure", host.output)
        self.assertLess(host.output.index("Battery drain while asleep: skipped"), host.output.index("Report written"))

    def test_declined_the_lid_is_never_watched(self):
        host = power_run(["n"], state=on_battery())

        self.assertEqual(check(host, power.SLEEP_DRAIN)["evidence"], ["skipped: you chose not to (it takes about ten minutes)"])
        self.assertNotIn(WATCH, host.commands_run)
        self.assertNotIn(power.PLUG_BACK, host.output)


class Stopped(LiveMac):
    """The run is stopped (the terminal closed) while the drain step watches the lid."""

    def run(self, argv):
        if list(argv) == WATCH:
            raise KeyboardInterrupt
        return super().run(argv)


class DrainCheckpointTest(unittest.TestCase):
    def stopped(self) -> str:
        first = Stopped(live_recording(), state=drain(), answers=[ENTER, "y"])
        self.assertEqual(main(ARGS, first, sections=(SECTIONS["power"],)), 130)
        saved = json.loads(first.written[CHECKPOINT])
        step = saved["shared"]["progress"]["power"]["drain"]
        self.assertEqual((step["since"], step["battery"]), (int(DRAIN_AT) - 1, "macsmc-battery"))
        self.assertEqual(saved["restorers"], [])  # the charge limit was put back before the lid closed
        return first.written[CHECKPOINT]

    def test_a_run_stopped_while_the_lid_was_closed_is_judged_from_the_log_and_the_battery(self):
        checkpoint = self.stopped()

        second = LiveMac(live_recording(checkpoint=checkpoint), state=drain(readings=[AFTER_DRAIN]), answers=[ENTER, ENTER, ENDED])
        self.assertEqual(main(ARGS, second, sections=(SECTIONS["power"],)), 0)

        result = check(second, power.SLEEP_DRAIN)
        self.assertEqual(result["status"], "pass")
        self.assertIn("read from the system log and the battery: the run had stopped while the lid was closed", result["evidence"])
        self.assertNotIn(WATCH, second.commands_run)
        self.assertNotIn(DRAIN_PROMPT, prompts(second))
        # The charge limit and idle results were kept: nothing is changed again.
        self.assertEqual([argv for argv in second.commands_run if argv[:2] == ["sudo", "-n"]], [])
        self.assertEqual(check(second, power.CHARGE_LIMIT)["status"], "pass")

    def test_a_mac_started_again_meanwhile_is_skipped(self):
        checkpoint = self.stopped()

        second = LiveMac(live_recording(checkpoint=checkpoint), state=drain(boot_id="5a1f0c3e-9d2b-4e87-b6a4-3c8e1f7d2b90"),
                         answers=[ENTER, ENTER, ENDED])
        self.assertEqual(main(ARGS, second, sections=(SECTIONS["power"],)), 0)

        self.assertIn("the Mac was started again since", check(second, power.SLEEP_DRAIN)["evidence"][0])


# -- privacy ---------------------------------------------------------------------------------------

class BatteryPrivacyTest(unittest.TestCase):
    def test_the_batterys_serial_date_model_and_cycle_count_are_never_read(self):
        class Reads(LiveMac):
            def read_file(self, path):
                self.state.__dict__.setdefault("read", []).append(path)
                return super().read_file(path)

        host = power_run(["y"], state=drain(), cls=Reads)

        private = ("serial_number", "manufacture_year", "manufacture_month", "manufacture_day", "cycle_count", "model_name", "uevent")
        battery_reads = [path for path in host.state.read if path.startswith(power.SMC_BATTERY)]
        self.assertTrue(battery_reads)
        self.assertEqual([path for path in battery_reads if path.rsplit("/", 1)[-1] in private], [])
        scripts = " ".join(" ".join(argv) for argv in host.commands_run if argv[:2] == ["sh", "-c"])
        for field in private:
            self.assertNotIn(field, scripts)
        self.assertEqual(check(host, power.SLEEP_DRAIN)["status"], "pass")

    def test_a_power_supply_uevent_is_scrubbed_of_the_batterys_serial_date_and_cycle_count(self):
        from omarchy_m_test.privacy import Scrubber

        scrubbed = Scrubber().scrub(
            "POWER_SUPPLY_NAME=macsmc-battery\nPOWER_SUPPLY_SERIAL_NUMBER=D8612345ABCX\nPOWER_SUPPLY_MANUFACTURE_YEAR=2023\n"
            "POWER_SUPPLY_MANUFACTURE_MONTH=4\nPOWER_SUPPLY_CYCLE_COUNT=87\nPOWER_SUPPLY_CAPACITY=81\nbattery D8612345ABCX\n"
        )
        self.assertEqual(scrubbed, (
            "POWER_SUPPLY_NAME=macsmc-battery\nPOWER_SUPPLY_SERIAL_NUMBER=<serial>\nPOWER_SUPPLY_MANUFACTURE_YEAR=<redacted>\n"
            "POWER_SUPPLY_MANUFACTURE_MONTH=<redacted>\nPOWER_SUPPLY_CYCLE_COUNT=<redacted>\nPOWER_SUPPLY_CAPACITY=81\nbattery <serial>\n"
        ))


if __name__ == "__main__":
    unittest.main()
