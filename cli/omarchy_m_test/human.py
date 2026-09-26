"""Human checks: the tool asks, the human answers yes, no or skip, with an optional note.

    result = human.check(ctx, "audio.speaker-tone", "Did you hear a short tone from both speakers?",
                         evidence=["played a 1 kHz tone at 30% volume"])

The result is a schema-v1 check of kind "human": yes passes, no fails, skip
(or no answer at all: end of input, Esc in gum, three answers that aren't
y/n/s) is skipped, never a failure. Its evidence holds what was asked, the
answer and the note, which passes the privacy scrubber like any evidence
before it reaches the checkpoint or the report. The check id must be in the
catalogue's checks, and in its section's human_checks so a skipped section
reports it as human too.

Ctrl-C at the question interrupts the run like anywhere else: the section's
restorers run and the run can resume.
"""

from __future__ import annotations

from typing import Sequence

from .session import Context
from .ui import Ui

STATUSES = {"yes": "pass", "no": "fail", "skip": "skip"}
NO_ANSWER = "answer: none (counted as skipped)"


def check(ctx: Context, check_id: str, question: str, evidence: Sequence[str] = ()) -> dict:
    """Ask the human `question` and return their answer as a human check result."""
    ui = ctx.ui or Ui(ctx.host)
    answer, note = ui.human(question)
    lines = [*evidence, f"asked: {question}"]
    lines.append(f"answer: {answer}" if answer else NO_ANSWER)
    if note:
        lines.append(f"note: {note}")
    return {"id": check_id, "kind": "human", "status": STATUSES.get(answer or "skip", "skip"), "evidence": lines}


def absent(ctx: Context, check_id: str) -> bool:
    """The catalogue says this Mac doesn't have what the check tests (no notch, no headphone jack): don't ask."""
    feature = ctx.catalogue.feature_for_check(check_id)
    if feature is None:
        return False
    states = ctx.catalogue.expected(feature, ctx.catalogue.chip_for_soc(ctx.machine.soc), ctx.machine.board)
    return any(state.get("status") == "absent" for state in (states or {}).values())


def skip(check_id: str, reason: str, evidence: Sequence[str] = ()) -> dict:
    """A human check that wasn't asked (its setup failed, the human declined a package): skipped, with why."""
    return {"id": check_id, "kind": "human", "status": "skip", "evidence": [*evidence, f"skipped: {reason}"]}
