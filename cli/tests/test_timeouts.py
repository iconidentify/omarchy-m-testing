"""Nothing a check runs can hang the run: a command that blocks ends in a skip within its time limit.

Two halves. The real host (RealHost) against commands that really block: a
child and a grandchild that never exit, a bundled script whose PipeWire call
never answers (the shim's own limit), and a bundled script that blocks
altogether. Then Seam A: the whole CLI against the recorded M2 Max where the
audio check script, or a pactl call in the live audio checks, timed out.
"""

from __future__ import annotations

import copy
import os
import shutil
import stat
import tempfile
import time
import types
import unittest
from unittest import mock

from omarchy_m_test import audio, bundled, host as host_module, scripts
from omarchy_m_test.host import RealHost, non_interactive, timeout_for
from tests.live_mac import live_recording
from tests.test_audio_display import run
from tests.test_interactive import check

CONVERGED = types.SimpleNamespace(stack="converged", describe=lambda: "the converged image")
AUDIO_IDS = ("audio.speaker-amps-unlocked", "audio.speaker-dsp", "audio.microphone-mapping")
HAS_TIMEOUT = shutil.which("timeout") is not None and os.name == "posix"


class _Scratch(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)

    def executable(self, name: str, text: str) -> str:
        path = os.path.join(self.dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)
        return path


@unittest.skipUnless(os.name == "posix", "the real host runs POSIX commands")
class RealHostTest(_Scratch):
    def test_a_command_whose_grandchild_never_exits_is_stopped_at_its_limit_with_what_it_printed(self):
        with mock.patch.object(host_module, "COMMAND_TIMEOUT_SECONDS", 1):
            started = time.monotonic()
            result = RealHost().run(["sh", "-c", "echo started; sleep 30 & sleep 30"])
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual((result.returncode, result.timed_out), (124, 1))
        self.assertIn("started", result.stdout)
        self.assertIn("timed out after 1s", result.stderr)

    def test_commands_read_nothing_page_nothing_and_sudo_never_asks(self):
        result = RealHost().run(["sh", "-c", 'read line; echo "read $? pager $PAGER $SYSTEMD_PAGER $GIT_PAGER"'])
        self.assertEqual(result.stdout.strip(), "read 1 pager cat cat cat")
        self.assertEqual(non_interactive(["sudo", "journalctl", "-k"]), ["sudo", "-n", "journalctl", "-k"])
        self.assertEqual(non_interactive(["sudo", "-n", "true"]), ["sudo", "-n", "true"])

    def test_ipc_tools_get_a_short_limit_and_everything_else_the_default(self):
        self.assertEqual(timeout_for(["pactl", "get-default-sink"]), host_module.IPC_TIMEOUT_SECONDS)
        self.assertEqual(timeout_for(["sudo", "-n", "wpctl", "status"]), host_module.IPC_TIMEOUT_SECONDS)
        self.assertEqual(timeout_for(["uname", "-r"]), host_module.COMMAND_TIMEOUT_SECONDS)


@unittest.skipUnless(HAS_TIMEOUT, "the shim needs timeout(1)")
class BundledScriptTimeoutTest(_Scratch):
    def audio_check(self, script: str, limit: int = 30) -> tuple[list[dict], float]:
        path = self.executable("apple-audio-check.sh", script)
        # A pactl that never answers: a wedged PipeWire-Pulse server.
        self.executable("pactl", "#!/bin/sh\nsleep 30\n")
        env = {"PATH": self.dir + os.pathsep + os.environ.get("PATH", "")}
        with mock.patch.object(bundled, "script_path", return_value=path), \
                mock.patch.dict(host_module.SHIMMED_PROGRAMS, {"pactl": 1}), \
                mock.patch.dict(host_module.BUNDLED_TIMEOUTS, {"apple-audio-check": limit}), \
                mock.patch.dict(os.environ, env):
            started = time.monotonic()
            results = scripts.audio_check(RealHost(), CONVERGED)
        return results, time.monotonic() - started

    def test_a_hung_pactl_skips_its_own_check_and_the_script_reports_the_rest(self):
        results, took = self.audio_check(
            "check() { if \"$@\" >/dev/null 2>&1; then echo \"PASS $1\"; else echo \"FAIL $1\"; fi; }\n"
            "echo 'PASS speaker amps unlocked this boot'\n"
            "if pactl list short sinks 2>/dev/null | grep -q convolver; then echo 'PASS speaker DSP sink present';"
            " else echo 'FAIL speaker DSP sink present'; fi\n"
            "echo 'PASS mic mapper running'\n"
        )
        self.assertLess(took, 20)
        by_id = {result["id"]: result for result in results}
        self.assertEqual({i: by_id[i]["status"] for i in AUDIO_IDS},
                         {"audio.speaker-amps-unlocked": "pass", "audio.speaker-dsp": "skip", "audio.microphone-mapping": "pass"})
        self.assertIn("skip: pactl timed out after 1s", by_id["audio.speaker-dsp"]["evidence"][0])

    def test_a_script_that_blocks_altogether_keeps_what_it_reported_and_skips_the_rest(self):
        results, took = self.audio_check("echo 'PASS speaker amps unlocked this boot'\nsleep 30\n", limit=1)
        self.assertLess(took, 10)
        by_id = {result["id"]: result for result in results}
        self.assertEqual(by_id["audio.speaker-amps-unlocked"]["status"], "pass")
        for check_id in ("audio.speaker-dsp", "audio.microphone-mapping"):
            self.assertEqual(by_id[check_id]["status"], "skip")
            self.assertEqual(by_id[check_id]["evidence"], ["skip: apple-audio-check timed out after 1s"])


def _timed_out(rec: dict, argv: list[str], seconds: int, stdout: str = "") -> dict:
    rec = copy.deepcopy(rec)
    rec["commands"] = [entry for entry in rec["commands"] if entry["argv"] != argv]
    rec["commands"].append({"argv": argv, "returncode": 124, "stdout": stdout,
                            "stderr": f"{argv[0]}: timed out after {seconds}s\n", "timed_out": seconds})
    return rec


class RecordedTimeoutTest(unittest.TestCase):
    """Seam A: the whole CLI, the Audio section only, on the recorded M2 Max."""

    def test_the_audio_script_timing_out_skips_its_checks_and_the_run_carries_on(self):
        rec = _timed_out(live_recording(), ["bundled:apple-audio-check", "--no-sound"], 90,
                         stdout="PASS audio stack installed\nPASS speaker amps unlocked this boot\n")
        host = run("audio", ["y", "s"], rec=rec)
        self.assertEqual(check(host, "audio.speaker-amps-unlocked")["status"], "pass")
        for check_id in ("audio.speaker-dsp", "audio.microphone-mapping"):
            result = check(host, check_id)
            self.assertEqual((result["status"], result["evidence"]), ("skip", ["skip: apple-audio-check timed out after 90s"]))
        self.assertEqual(check(host, "audio.speaker-tone")["status"], "pass")

    def test_a_pactl_call_timing_out_skips_the_rest_of_the_section_never_fails_it(self):
        host = run("audio", rec=_timed_out(live_recording(), audio.DEFAULT_SOURCE, 15))
        self.assertEqual(check(host, "audio.speaker-dsp")["status"], "pass")  # the script had already reported
        for check_id in ("audio.microphone-signal", "audio.speaker-tone", "audio.headphone-detection"):
            result = check(host, check_id)
            self.assertEqual(result["status"], "skip")
            self.assertIn("skip: timed out after 15s (pactl get-default-source)", result["evidence"][0])
        self.assertNotIn("fail", {check(host, i)["status"] for i in AUDIO_IDS})


if __name__ == "__main__":
    unittest.main()
