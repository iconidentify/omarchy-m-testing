"""Seam A: checkpoints and the restorer registry, through the whole CLI.

The Tone test section (tests/desktop.py) turns the volume down and mutes the
speaker through the registry, then asks the human something: the tests
interrupt it there (Ctrl-C), make a later command fail, or kill the host
outright, and assert on the commands the Mac was sent and the checkpoint left.
"""

from __future__ import annotations

import json
import os
import unittest

from omarchy_m_test.app import main
from omarchy_m_test.recording import ENDED, EOF, INTERRUPT, RecordedHost
from omarchy_m_test.session import Section
from tests.corpus import MACHINES, forbidden, raw_recording
from tests.desktop import (
    BENCHMARK_OFFER, CHECKPOINT, HUMAN_QUESTIONS, LISTEN, MUTE, SECTIONS, UNANSWERED, UNMUTE, VOLUME_BACK, VOLUME_DOWN,
    host, recording, with_home, with_section_commands,
)

HERE = os.path.dirname(os.path.abspath(__file__))
GOLDEN = os.path.join(os.path.dirname(os.path.dirname(HERE)), "schema", "golden", "m2-max-image2.json")
REPORT_FILE = "omarchy-m-test-report.json"
ENTER = ""
RESUME = "Resume where it stopped? [Y/n] "


def _tone_mac(base, answers, checkpoint=None, restore_returncode=0, cls=RecordedHost) -> RecordedHost:
    rec = with_section_commands(with_home(base, checkpoint=checkpoint), restore_returncode)
    return cls(rec, answers=list(answers))


def tone_mac(answers, checkpoint=None, restore_returncode=0, cls=RecordedHost) -> RecordedHost:
    """The recorded M2 with $HOME set, running every section plus Tone."""
    return _tone_mac(recording(), answers, checkpoint, restore_returncode, cls)




def after(mac: RecordedHost, argv: list[str]) -> list[list[str]]:
    """The commands sent after the first `argv`."""
    return mac.commands_run[mac.commands_run.index(argv) + 1:]


def prompts(mac: RecordedHost) -> list[str]:
    return [event[1] for event in mac.transcript if event[0] == "prompt"]


class RestorerTest(unittest.TestCase):
    def test_changes_are_undone_newest_first_when_the_section_ends(self):
        mac = tone_mac([ENTER, *UNANSWERED, "y"])

        status = main(["--dry-run"], mac, sections=SECTIONS)

        self.assertEqual(status, 0)
        self.assertEqual(after(mac, VOLUME_DOWN), [MUTE, UNMUTE, VOLUME_BACK])
        self.assertNotIn(CHECKPOINT, mac.written)

    def test_ctrl_c_mid_section_undoes_every_change_and_keeps_the_checkpoint(self):
        mac = tone_mac([ENTER, *UNANSWERED, INTERRUPT])

        status = main(["--dry-run"], mac, sections=SECTIONS)

        self.assertEqual(status, 130)
        self.assertEqual(after(mac, MUTE), [UNMUTE, VOLUME_BACK])
        self.assertIn("Interrupted", mac.output)
        self.assertIn("put back", mac.output)
        self.assertNotIn(REPORT_FILE, mac.written)
        saved = json.loads(mac.written[CHECKPOINT])
        self.assertEqual(saved["restorers"], [])
        self.assertEqual(list(saved["done"]), [s.id for s in SECTIONS[:-1] if not s.disruptive])  # over SSH: no Sleep

    def test_an_error_mid_section_undoes_every_change_then_surfaces(self):
        class Broken(RecordedHost):
            def prompt(self, message):
                if message == LISTEN:
                    raise RuntimeError("the check fell over")
                return super().prompt(message)

        mac = tone_mac([ENTER, *UNANSWERED], cls=Broken)

        with self.assertRaises(RuntimeError):
            main(["--dry-run"], mac, sections=SECTIONS)

        self.assertEqual(after(mac, MUTE), [UNMUTE, VOLUME_BACK])

    def test_the_restorer_is_registered_before_the_change_is_made(self):
        class DiesOnChange(RecordedHost):
            def run(self, argv):
                if list(argv) == VOLUME_DOWN:
                    saved = json.loads(self.written[CHECKPOINT])
                    registered.extend(r["argv"] for r in saved["restorers"])
                return super().run(argv)

        registered: list[list[str]] = []
        main(["--dry-run"], tone_mac([ENTER, *UNANSWERED, "y"], cls=DiesOnChange), sections=SECTIONS)

        self.assertEqual(registered, [VOLUME_BACK])

    def test_a_run_killed_outright_has_its_changes_undone_by_the_next_run_first(self):
        class Killed(RecordedHost):
            """The process dies at the prompt: nothing after it reaches the Mac."""
            dead = False

            def prompt(self, message):
                if message == LISTEN:
                    self.dead = True
                    raise SystemExit(137)
                return super().prompt(message)

            def run(self, argv):
                if self.dead:
                    raise SystemExit(137)
                return super().run(argv)

        first = tone_mac([ENTER, *UNANSWERED], cls=Killed)
        with self.assertRaises(SystemExit):
            main(["--dry-run"], first, sections=SECTIONS)
        left = first.written[CHECKPOINT]
        self.assertEqual([r["argv"] for r in json.loads(left)["restorers"]], [VOLUME_BACK, UNMUTE])

        # The next run puts things back before it even shows the disclaimer, whatever the answer.
        second = tone_mac(["n"], checkpoint=left)
        status = main([], second, sections=SECTIONS)

        self.assertEqual(status, 1)
        self.assertEqual(second.commands_run[-2:], [UNMUTE, VOLUME_BACK])
        self.assertIn("the speaker volume", second.output)
        self.assertNotIn(CHECKPOINT, second.written)  # declined: the earlier run is over too
        self.assertIn(CHECKPOINT, second.removed)

    def test_a_restorer_that_fails_tells_the_human_how_to_undo_it_by_hand(self):
        mac = tone_mac([ENTER, *UNANSWERED, "y"], restore_returncode=1)

        status = main(["--dry-run"], mac, sections=SECTIONS)

        self.assertEqual(status, 0)
        self.assertIn("Couldn't undo: the speaker volume (no default sink)", mac.output)
        self.assertIn(" ".join(VOLUME_BACK), mac.output)


class CheckpointTest(unittest.TestCase):
    def interrupted(self) -> str:
        mac = tone_mac([ENTER, *UNANSWERED, INTERRUPT])
        main(["--dry-run"], mac, sections=SECTIONS)
        return mac.written[CHECKPOINT]

    def test_an_interrupted_run_resumes_where_it_stopped(self):
        checkpoint = self.interrupted()
        mac = tone_mac([ENTER, ENTER, "y"], checkpoint=checkpoint)

        status = main(["--dry-run"], mac, sections=SECTIONS)

        self.assertEqual(status, 0)
        self.assertIn(RESUME, prompts(mac))
        self.assertIn("left to run: Tone", mac.output)
        # The interrupted Tone section runs again; the finished System section's results come from the checkpoint.
        self.assertIn(VOLUME_DOWN, mac.commands_run)
        self.assertIn(LISTEN, prompts(mac))
        with open(GOLDEN, encoding="utf-8") as f:
            self.assertEqual(mac.written[REPORT_FILE], f.read())
        self.assertNotIn(CHECKPOINT, mac.written)

    def test_finished_sections_are_not_run_again(self):
        saved = json.loads(self.interrupted())
        saved["done"]["boot"][0]["evidence"] = ["kept from the checkpoint"]
        mac = tone_mac([ENTER, ENTER, "y"], checkpoint=json.dumps(saved))

        main(["--dry-run"], mac, sections=SECTIONS)

        report = json.loads(mac.written[REPORT_FILE])
        self.assertEqual(report["checks"][0]["evidence"], ["kept from the checkpoint"])
        self.assertIn(CHECKPOINT, mac.removed)

    def test_declining_to_resume_starts_over(self):
        mac = tone_mac([ENTER, "n", *UNANSWERED, "y"], checkpoint=self.interrupted())

        status = main(["--dry-run"], mac, sections=SECTIONS)

        self.assertEqual(status, 0)
        self.assertIn("Checking Apple MacBook Pro", mac.output)
        self.assertIn("system.identity", mac.output.split(RESUME)[-1])

    def test_a_checkpoint_from_another_kernel_or_tool_version_is_not_resumed(self):
        for field, value in (("kernel", "7.2.0-1-ARCH"), ("tool_version", "0.0.9")):
            with self.subTest(field=field):
                saved = json.loads(self.interrupted())
                saved["key"][field] = value
                mac = tone_mac([ENTER, *UNANSWERED, "y"], checkpoint=json.dumps(saved))

                status = main(["--dry-run"], mac, sections=SECTIONS)

                self.assertEqual(status, 0)
                self.assertNotIn(RESUME, prompts(mac))

    def test_skip_still_applies_to_the_sections_left_when_resuming(self):
        mac = tone_mac([ENTER, ENTER], checkpoint=self.interrupted())

        status = main(["--dry-run", "--skip", "tone"], mac, sections=SECTIONS)

        self.assertEqual(status, 0)
        self.assertNotIn(VOLUME_DOWN, mac.commands_run)

    def test_ctrl_c_after_the_report_is_written_offers_no_resume(self):
        mac = tone_mac([ENTER, *UNANSWERED, "y", INTERRUPT])

        status = main([], mac, sections=SECTIONS)

        self.assertEqual(status, 130)
        self.assertIn(REPORT_FILE, mac.written)
        self.assertNotIn("resume", mac.output.split("Interrupted")[-1])

    def test_ctrl_c_mid_run_says_it_can_resume(self):
        mac = tone_mac([ENTER, *UNANSWERED, INTERRUPT])

        main(["--dry-run"], mac, sections=SECTIONS)

        self.assertIn("resume where it stopped", mac.output.split("Interrupted")[-1])

    def test_a_damaged_checkpoint_is_ignored(self):
        mac = tone_mac([ENTER, *UNANSWERED, "y"], checkpoint="{not json")

        self.assertEqual(main(["--dry-run"], mac, sections=SECTIONS), 0)
        self.assertNotIn(RESUME, prompts(mac))

    def test_record_mode_neither_reads_nor_writes_a_checkpoint(self):
        rec = with_home(recording())
        del rec["files"][CHECKPOINT]  # a read would raise RecordingMiss
        mac = host(rec, answers=[ENTER, ENDED])

        status = main(["--dry-run", "--record", "m.json"], mac)

        self.assertEqual(status, 0)
        self.assertEqual(sorted(mac.written), ["m.json", REPORT_FILE])



class CheckpointPrivacyTest(unittest.TestCase):
    def test_the_checkpoint_is_private_and_holds_only_scrubbed_evidence(self):
        for machine in MACHINES:
            with self.subTest(machine=machine):
                # The real, unscrubbed evidence, interrupted in the Tone section after every other section ran.
                mac = _tone_mac(raw_recording(machine), [ENTER, *[EOF] * HUMAN_QUESTIONS[machine], *BENCHMARK_OFFER, INTERRUPT])

                self.assertEqual(main(["--dry-run"], mac, sections=SECTIONS), 130)

                self.assertIn(CHECKPOINT, mac.private)
                text = mac.written[CHECKPOINT]
                # Over SSH the disruptive sections (Sleep) aren't run, so they aren't done either.
                self.assertEqual(len(json.loads(text)["done"]), len([s for s in SECTIONS if not s.disruptive]) - 1)
                for identifier in forbidden(machine):
                    self.assertNotIn(identifier, text)

    def test_declining_the_disclaimer_deletes_an_earlier_runs_checkpoint(self):
        left = tone_mac([ENTER, *UNANSWERED, INTERRUPT])
        main(["--dry-run"], left, sections=SECTIONS)

        mac = tone_mac(["n"], checkpoint=left.written[CHECKPOINT])
        status = main(["--dry-run"], mac, sections=SECTIONS)

        self.assertEqual(status, 1)
        self.assertIn(CHECKPOINT, mac.removed)


if __name__ == "__main__":
    unittest.main()


# -- serials the scrubber learned survive a resume ------------------------------------------

USB_SERIAL = "201405280001"
HEADPHONES = "Marcelo's AirPods Pro"


def _cards(ctx):
    return [{"id": "audio.sound-cards", "kind": "automatic", "status": "pass",
             "evidence": [f'device.serial = "Generic_USB_Audio_{USB_SERIAL}"', f"Device 7C:C1:80:12:34:56 {HEADPHONES}"]}]


def _sinks(ctx):
    ctx.host.prompt(LISTEN)
    return [{"id": "audio.default-sink", "kind": "automatic", "status": "pass",
             "evidence": [f"default sink: alsa_output.usb-Generic_USB_Audio_{USB_SERIAL}-00.analog-stereo", f"last output: {HEADPHONES}"]}]


CARDS = Section("cards", "Cards", "Names the sound cards.", ("audio.sound-cards",), _cards)
SINKS = Section("sinks", "Sinks", "Names the default sink.", ("audio.default-sink",), _sinks)


class LearnedSerialsTest(unittest.TestCase):
    def test_a_serial_or_device_name_one_section_named_is_removed_from_a_section_run_after_resuming(self):
        first = RecordedHost(with_home(recording()), answers=[ENTER, INTERRUPT])
        self.assertNotEqual(main(["--dry-run"], first, sections=(CARDS, SINKS)), 0)
        checkpoint = first.written[CHECKPOINT]
        self.assertEqual(json.loads(checkpoint)["done"]["cards"][0]["evidence"], ['device.serial = "<serial>"', "Device <mac> <device-name>"])

        second = RecordedHost(with_home(recording(), checkpoint=checkpoint), answers=[ENTER, ENTER, "y"])
        self.assertEqual(main(["--dry-run"], second, sections=(CARDS, SINKS)), 0)

        report = json.loads(second.written[REPORT_FILE])
        self.assertNotIn(USB_SERIAL, second.written[REPORT_FILE])
        self.assertEqual(report["checks"][1]["evidence"], ["default sink: alsa_output.usb-<serial>-00.analog-stereo", "last output: <device-name>"])
        self.assertNotIn("Marcelo", second.written[REPORT_FILE])
