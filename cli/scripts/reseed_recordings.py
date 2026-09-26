#!/usr/bin/env python3
"""Regenerate tests/recordings/<machine>.json and schema/golden/<machine>.json from the evidence corpus.

Runs the whole CLI in record mode (--dry-run --record) against each corpus
machine in tests/corpus/ and saves what record mode wrote, keeping the
recording's hand-written description and source, and the report as the
golden report. The Seam A tests check the committed recordings and golden
reports equal what the CLI produces, so run this after changing the corpus,
the scrubber, the recorded sources, the checks or the catalogue, and review
the golden diff: the site's Seam B tests post those reports.

    python3 scripts/reseed_recordings.py
"""

import json
import os
import sys

CLI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CLI)

from omarchy_m_test.app import main  # noqa: E402
from omarchy_m_test.recording import ENDED  # noqa: E402
from tests.corpus import MACHINES, raw_host, raw_recording, seeded_recording_path  # noqa: E402

OUT = "recording.json"
REPORT = "omarchy-m-test-report.json"
GOLDEN = os.path.join(os.path.dirname(CLI), "schema", "golden")


def reseed(machine: str) -> str:
    # The disclaimer accepted, then no answers: the human checks are asked and recorded as not answered.
    host = raw_host(machine, answers=["", ENDED])
    status = main(["--dry-run", "--record", OUT], host)
    if status != 0:
        raise SystemExit(f"{machine}: the CLI exited {status}")
    recording = json.loads(host.written[OUT])

    path = seeded_recording_path(machine)
    raw = raw_recording(machine)
    recording["description"] = raw["description"].replace(": raw host answers for record mode", "")
    recording["source"] = f"omarchy-m-test --record against tests/corpus/{machine}/ (scrubbed). {raw['source']}"
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(recording, indent=2, ensure_ascii=False) + "\n")
    with open(os.path.join(GOLDEN, f"{machine}.json"), "w", encoding="utf-8") as f:
        f.write(host.written[REPORT])
    return path


if __name__ == "__main__":
    for name in MACHINES:
        print(f"wrote {reseed(name)}")
