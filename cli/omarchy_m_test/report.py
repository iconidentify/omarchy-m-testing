"""The schema-v1 report (schema/report-v1.schema.json)."""

from __future__ import annotations

import json

from . import SCHEMA_VERSION, TOOL_NAME, TOOL_VERSION
from .consent import CONSENT_VERSION
from .machine import Machine


def build(machine: Machine, checks: list[dict]) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
        "consent_version": CONSENT_VERSION,
        "machine": {
            "model": machine.model,
            "board": machine.board,
            "soc": machine.soc,
            "chip": machine.chip,
            "arch": machine.arch,
            "kernel": machine.kernel,
        },
        "checks": checks,
    }


def to_text(report: dict) -> str:
    """The exact text that is written, shown and uploaded."""
    return json.dumps(report, indent=2, ensure_ascii=False) + "\n"
