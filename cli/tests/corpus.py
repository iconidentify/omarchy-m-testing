"""The recorded-Mac corpus: real (pseudonymized) evidence as raw host answers.

tests/corpus/<machine>/host.json is a recording whose outputs may point at
evidence files beside it ({"corpus": "kernel.log"}) and whose entries may
carry a "note" on provenance, and "env" the environment variables the run
read (m1-pro-converged ran over SSH). It is what the Mac answered before scrubbing,
so record mode can be run against it; "forbidden" lists the identifiers in
it that must never reach a recording or a report.

tests/recordings/<machine>.json is what record mode saved from it
(scripts/reseed_recordings.py regenerates them).
"""

from __future__ import annotations

import json
import os
from typing import Any

from omarchy_m_test.recording import RECORDING_VERSION, RecordedHost

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(HERE, "corpus")
RECORDINGS = os.path.join(HERE, "recordings")
MACHINES = ("m2-max-image2", "m1-pro-mx-mac", "m1-pro-converged", "m2-max-converged")


def _manifest(machine: str) -> dict[str, Any]:
    with open(os.path.join(CORPUS, machine, "host.json"), encoding="utf-8") as f:
        return json.load(f)


def _resolve(machine: str, value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"corpus"}:
        with open(os.path.join(CORPUS, machine, value["corpus"]), encoding="utf-8") as f:
            return f.read()
    return value


def raw_recording(machine: str) -> dict[str, Any]:
    manifest = _manifest(machine)
    commands = []
    for entry in manifest["commands"]:
        entry = {key: _resolve(machine, value) for key, value in entry.items() if key != "note"}
        commands.append(entry)
    files = {
        path: None if entry is None else {key: _resolve(machine, value) for key, value in entry.items() if key != "note"}
        for path, entry in manifest["files"].items()
    }
    return {
        "recording_version": RECORDING_VERSION,
        "description": manifest["description"],
        "source": manifest["source"],
        "commands": commands,
        "files": files,
        "dirs": manifest["dirs"],
        # The environment the run saw (a run over SSH skips its disruptive sections).
        **({"env": manifest["env"]} if "env" in manifest else {}),
    }


def raw_host(machine: str, **kwargs: Any) -> RecordedHost:
    """A host answering with the unscrubbed evidence, as the real Mac would."""
    return RecordedHost(raw_recording(machine), **kwargs)


def forbidden(machine: str) -> list[str]:
    return list(_manifest(machine)["forbidden"])


def seeded_recording_path(machine: str) -> str:
    return os.path.join(RECORDINGS, f"{machine}.json")
