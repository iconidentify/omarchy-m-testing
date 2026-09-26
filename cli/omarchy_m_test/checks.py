"""Checks. Each check returns one schema-v1 check result."""

from __future__ import annotations

from .machine import Machine


def system_identity(machine: Machine) -> dict:
    """Automatic check: the Mac's model, chip and kernel were identified."""
    evidence = [
        f"model: {machine.model}",
        f"compatible: {' '.join(machine.compatible)}",
        f"chip: {machine.chip} ({machine.soc})",
        f"kernel: {machine.kernel}",
    ]
    identified = machine.chip != "unknown" and machine.kernel != "unknown"
    return {
        "id": "system.identity",
        "kind": "automatic",
        "status": "pass" if identified else "fail",
        "evidence": evidence,
    }
