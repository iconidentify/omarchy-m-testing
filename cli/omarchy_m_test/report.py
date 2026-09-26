"""The schema-v1 report (schema/report-v1.schema.json)."""

from __future__ import annotations

import json

from . import SCHEMA_VERSION, TOOL_NAME, TOOL_VERSION
from .catalogue import Catalogue
from .consent import CONSENT_VERSION
from .machine import Machine


def build(machine: Machine, system: dict, checks: list[dict], catalogue: Catalogue) -> dict:
    """The report, with every check result explained against the catalogue."""
    classified = [{**check, "classification": catalogue.classify(check, machine.soc, machine.board)} for check in checks]
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
        "consent_version": CONSENT_VERSION,
        "catalogue_version": catalogue.version,
        "machine": {
            "model": machine.model,
            "board": machine.board,
            "soc": machine.soc,
            "chip": machine.chip,
            "arch": machine.arch,
            "kernel": machine.kernel,
        },
        "system": system,
        "checks": classified,
    }


def to_text(report: dict) -> str:
    """The exact text that is written, shown and uploaded."""
    return json.dumps(report, indent=2, ensure_ascii=False) + "\n"
