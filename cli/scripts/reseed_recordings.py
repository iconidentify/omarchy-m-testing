#!/usr/bin/env python3
"""Regenerate tests/recordings/<machine>.json from the evidence corpus.

Runs the whole CLI in record mode (--dry-run --record) against each corpus
machine in tests/corpus/ and saves what record mode wrote, keeping the
recording's hand-written description and source. The Seam A tests check the
committed recordings equal what record mode produces, so run this after
changing the corpus, the scrubber or the recorded sources.

    python3 scripts/reseed_recordings.py
"""

import json
import os
import sys

CLI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, CLI)

from omarchy_m_test.app import main  # noqa: E402
from tests.corpus import MACHINES, raw_host, raw_recording, seeded_recording_path  # noqa: E402

OUT = "recording.json"


def reseed(machine: str) -> str:
    host = raw_host(machine, answers=[""])
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
    return path


if __name__ == "__main__":
    for name in MACHINES:
        print(f"wrote {reseed(name)}")
