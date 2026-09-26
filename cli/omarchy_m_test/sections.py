"""The sections of a run on an Apple Silicon Mac, in order.

Each section names the check ids it reports, so a skipped section still
reports every one of its checks (as skipped). Titles are drawn in the logo's
font, which has letters and spaces only; keep them short.
"""

from __future__ import annotations

from . import checks
from .session import Context, Section


def _system(ctx: Context) -> list[dict]:
    return [checks.system_identity(ctx.machine)]


APPLE: tuple[Section, ...] = (
    Section("system", "System", "This Mac's model, chip and kernel.", ("system.identity",), _system),
)
