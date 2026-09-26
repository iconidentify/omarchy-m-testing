"""A run's sections, the restorer registry and the checkpoint.

Sections: a run is a list of sections (sections.py), listed up front. The
human can skip any of them (the picker at a terminal, --skip anywhere); a
skipped section's checks are reported as skipped, never as failures.

Restorers: a section that changes the machine does it through
Changes.make(description, change, restore), which registers the command that
undoes it *before* making the change. Restorers run, newest first, when the
section ends, on an error and on an interrupt. They are kept in the
checkpoint too, so a run killed outright (power loss, a closed terminal
before the signal handler ran) has them run by the next run, before anything
else.

Checkpoint: after each section, the run's state (the sections chosen, the
results of the finished ones, pending restorers) is written to
$XDG_STATE_HOME/omarchy-m-test/checkpoint.json (~/.local/state/...). A run that
finds one for the same tool, catalogue, Mac and kernel offers to resume: the
finished sections aren't run again, the interrupted one starts over. The
checkpoint is removed once the report is written.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from .catalogue import Catalogue
from .host import CommandResult, Host
from .machine import Machine

CHECKPOINT_VERSION = 1
CHECKPOINT_NAME = "omarchy-m-test/checkpoint.json"
SKIPPED_EVIDENCE = "skipped: this section wasn't run"


@dataclass(frozen=True)
class Restorer:
    description: str
    argv: tuple[str, ...]


class Changes:
    """The restorer registry."""

    def __init__(self, host: Host, persist: Callable[[], None] = lambda: None):
        self.host = host
        self.persist = persist
        self.pending: list[Restorer] = []
        self.failed: list[tuple[Restorer, str]] = []

    def make(self, description: str, change: Sequence[str], restore: Sequence[str], host: Host | None = None) -> CommandResult:
        """Register how to undo a change, then make it."""
        self.register(description, restore)
        return (host or self.host).run(list(change))

    def register(self, description: str, restore: Sequence[str]) -> None:
        self.pending.append(Restorer(description, tuple(restore)))
        self.persist()

    def restore(self) -> None:
        """Undo every pending change, newest first.

        A restorer that fails is reported and dropped (retrying it forever would
        help nobody). If the host itself gives out, the rest stay pending in the
        checkpoint for the next run.
        """
        while self.pending:
            restorer = self.pending[-1]
            try:
                result = self.host.run(list(restorer.argv))
            except Exception:
                return
            self.pending.pop()
            if result.returncode != 0:
                self.failed.append((restorer, (result.stderr or result.stdout).strip()))
            try:
                self.persist()
            except Exception:
                return

    def take_failures(self) -> list[tuple[Restorer, str]]:
        failed, self.failed = self.failed, []
        return failed


@dataclass(frozen=True)
class Context:
    """What a section's checks work with."""

    host: Host
    machine: Machine
    catalogue: Catalogue
    changes: Changes

    def change(self, description: str, change: Sequence[str], restore: Sequence[str]) -> CommandResult:
        """Change the machine: `restore` is registered first, and runs when the section ends."""
        return self.changes.make(description, change, restore, self.host)


@dataclass(frozen=True)
class Section:
    id: str
    title: str                 # drawn in the logo's font: short, letters and spaces
    description: str
    check_ids: tuple[str, ...]  # reported as skipped when the section is
    run: Callable[[Context], list[dict]]


def skipped(section: Section) -> list[dict]:
    return [{"id": check_id, "kind": "automatic", "status": "skip", "evidence": [SKIPPED_EVIDENCE]} for check_id in section.check_ids]


@dataclass
class State:
    """What the checkpoint holds."""

    selected: list[str]
    done: dict[str, list[dict]] = field(default_factory=dict)
    restorers: list[Restorer] = field(default_factory=list)
    key: dict[str, Any] = field(default_factory=dict)

    def to_text(self) -> str:
        return json.dumps({
            "checkpoint_version": CHECKPOINT_VERSION,
            "key": self.key,
            "selected": self.selected,
            "done": self.done,
            "restorers": [{"description": r.description, "argv": list(r.argv)} for r in self.restorers],
        }, indent=2, ensure_ascii=False) + "\n"

    @classmethod
    def from_text(cls, text: str | bytes) -> "State | None":
        try:
            data = json.loads(text)
            if data.get("checkpoint_version") != CHECKPOINT_VERSION:
                return None
            restorers = [Restorer(str(r["description"]), tuple(str(a) for a in r["argv"])) for r in data.get("restorers", [])]
            done = {str(k): list(v) for k, v in data.get("done", {}).items()}
            return cls([str(s) for s in data.get("selected", [])], done, restorers, dict(data.get("key", {})))
        except (ValueError, TypeError, KeyError, AttributeError):
            return None


def run_key(machine: Machine, catalogue: Catalogue, version: str) -> dict[str, Any]:
    """A checkpoint is only resumed by the same tool and catalogue on the same Mac and kernel."""
    return {"tool_version": version, "catalogue_version": catalogue.version, "board": machine.board, "kernel": machine.kernel}


class Checkpoint:
    def __init__(self, host: Host, path: str | None):
        self.host = host
        self.path = path

    @classmethod
    def for_host(cls, host: Host, enabled: bool = True) -> "Checkpoint":
        if not enabled:
            return cls(host, None)
        base = host.env("XDG_STATE_HOME")
        if not base:
            home = host.env("HOME")
            base = f"{home}/.local/state" if home else None
        return cls(host, f"{base}/{CHECKPOINT_NAME}" if base else None)

    def load(self) -> State | None:
        if not self.path:
            return None
        try:
            text = self.host.read_file(self.path)
        except OSError:
            return None
        return State.from_text(text)

    def save(self, state: State) -> None:
        if self.path:
            self.host.write_file(self.path, state.to_text())

    def clear(self) -> None:
        if self.path:
            self.host.remove_file(self.path)
