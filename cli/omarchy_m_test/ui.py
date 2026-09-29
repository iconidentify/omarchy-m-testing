"""What the human sees: plain text, or Omarchy's installer look at a terminal.

Ui.for_host picks one. Off a terminal (a pipe, a test) the run prints plain
lines and prompts with host.prompt, nothing else. At a terminal it looks like
Omarchy's installer: the screen cleared, the installed logo centred in the
theme's green, section titles in plain bold text in the theme's accent over a
thin rule (the terminal's own monospace font, never a FIGlet one), gum
prompts, and during automatic checks a live feed: the last lines of what the
checks run and read, redrawn in place in grey, each prefixed "  → "
(install/helpers/logging.sh).

Everything at a terminal is wrapped to one text column, the logo's width
(at least 80), lined up under the logo's left edge: a wrapped line carries
on under the start of its own text (a hanging indent after a list number, a
"- " or a result's PASS/FAIL/SKIP), never back at the terminal's left edge.

Progress: each section starts with where the run is, "Section 4/13 · Audio",
and a bar across every section the run has, each weighted by how many checks
it reports (done, this one, still to come). At a terminal the same line stays
under the live feed while the section runs; off one it's plain ASCII
("Section 4/13 - Audio [###===---] 31%").

Every question defaults to yes: it shows [Y/n] (a human check [Y/n/s]) and
a bare Enter answers yes. Ui.confirm asks before an action (reload the Wi-Fi
driver, close the lid, upload): Enter goes ahead, n doesn't, end of input
never does. Human checks (human.py) ask with Ui.human, one line in every UI
("n the left speaker crackles"): yes, no or skip, plus an optional note. A
bare Enter there is a yes too, but one nobody typed: Ui.human says so, and
the report marks the result answered_by_default, which the site shows as
unconfirmed and never counts. In the middle of a section every prompt goes
through the section's feed, which it lifts while asking.
"""

from __future__ import annotations

import re
import textwrap
from collections import deque
from dataclasses import dataclass
from typing import Sequence

from . import TOOL_NAME, TOOL_VERSION
from .host import Bounded, CommandResult, Host, Terminal
from .theme import Theme, load, with_padding

ESC = "\033["
RESET = ESC + "0m"
BOLD = ESC + "1m"
CLEAR_SCREEN = ESC + "H" + ESC + "2J"
CLEAR_LINE = ESC + "2K"
CLEAR_BELOW = ESC + "J"
HIDE_CURSOR = ESC + "?25l"
SHOW_CURSOR = ESC + "?25h"
FEED_PREFIX = "  → "
FEED_MAX_ROWS = 20
FEED_MIN_ROWS = 3
FEED_ROWS_PER_LINE = 3  # a long command or output line wraps to at most this many rows
RULE = "─"
PROGRESS_BAR_WIDTH = 30
# What a wrapped line hangs under: a list number, a dash or arrow, or a result's status word.
_HANG = re.compile(r"^(\s*(?:\d+\.\s+(?:skip\s+|\s{4}\s)?|[-*→]\s+|(?:PASS|FAIL|SKIP|INFO|GAP|N/A)\s+)?)")

# The site's colour code, per classification outcome.
OUTCOME_COLOURS = {
    "works": "green",
    "fails": "red",
    "regression": "red",
    "partial": "yellow",
    "not-in-omarchy": "blue",
    "not-in-aurora": "blue",
    "not-in-asahi": "blue",
    "unknown-hardware": "magenta",
}
HUMAN_WORDS = {"y": "yes", "yes": "yes", "n": "no", "no": "no", "s": "skip", "skip": "skip"}
HUMAN_HINT = (
    "Answer y (yes), n (no) or s (skip); Enter alone is yes. A note can follow the letter, "
    'e.g. "n the left speaker crackles". Type y when you checked: an Enter-only yes is '
    "recorded as unconfirmed. Skipping is never counted as a failure."
)
HUMAN_TRIES = 3
_CONTROL = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|[\x00-\x08\x0b-\x1f\x7f]")


@dataclass(frozen=True)
class Progress:
    """Where a run is: section `number` of `count`, and the checks before it, in it and in all (the bar's weights)."""

    number: int
    count: int
    title: str
    done: int
    current: int
    total: int

    @property
    def label(self) -> str:
        return f"Section {self.number}/{self.count} · {self.title}"

    @property
    def percent(self) -> int:
        return round(100 * self.done / self.total) if self.total else 0

    def cells(self, width: int) -> tuple[int, int, int]:
        """The bar's done, current and still-to-come cells, `width` in all (this section always shows)."""
        if not self.total:
            return 0, 0, width
        done = min(width, round(width * self.done / self.total))
        current = min(width - done, max(1, round(width * (self.done + self.current) / self.total) - done))
        return done, current, width - done - current

    def plain(self) -> str:
        """ASCII only, off a terminal: "Section 4/13 - Audio [#####=====----] 31%"."""
        done, current, rest = self.cells(PROGRESS_BAR_WIDTH)
        return f"Section {self.number}/{self.count} - {self.title} [{'#' * done}{'=' * current}{'-' * rest}] {self.percent}%"


def progress_of(sections: Sequence, number: int, done_ids: set[str]) -> Progress:
    """The progress at the start of sections[number - 1], `sections` being the ones this run runs, in order."""
    weights = [max(1, len(section.check_ids)) for section in sections]
    current = sections[number - 1]
    done = sum(weight for section, weight in zip(sections, weights) if section.id in done_ids and section is not current)
    return Progress(number, len(sections), current.title, done, weights[number - 1], sum(weights))


class Interrupted(KeyboardInterrupt):
    """Ctrl-C in a gum prompt (gum exits 130)."""


def _rgb(hex_colour: str) -> str:
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return f"{ESC}38;2;{r};{g};{b}m"


def wrap(text: str, width: int) -> list[str]:
    """`text` as lines at most `width` wide; a wrapped line hangs under its own text (see the module docstring)."""
    lines: list[str] = []
    for line in _reflowed(text.split("\n")):
        if len(line) <= width or not line.strip():
            lines.append(line)
            continue
        hang = _HANG.match(line).group(1)
        if len(hang) > width // 2:
            hang = re.match(r"\s*", line).group(0)[: width // 2]
        lines += textwrap.wrap(
            line[len(hang):], width, initial_indent=hang, subsequent_indent=" " * len(hang),
            break_long_words=True, break_on_hyphens=False,
        ) or [line]
    return lines


def _reflowed(lines: list[str]) -> list[str]:
    """Lines already wrapped under a hanging indent joined back to their item, to wrap again at this width."""
    joined: list[str] = []
    hang = ""
    for line in lines:
        marker = _HANG.match(line).group(1)
        continues = joined and hang.strip() == "" and len(hang) > 0 and line.startswith(hang) and line.strip() \
            and not line[len(hang)].isspace() and marker.strip() == ""
        if continues:
            joined[-1] += " " + line.strip()
            continue
        joined.append(line)
        hang = " " * len(marker) if marker.strip() else ""
    return joined


def printable(text: str) -> str:
    """A line of command output made safe to draw: no escape sequences, tabs as spaces."""
    return _CONTROL.sub("", text.expandtabs(4)).rstrip()


class Ui:
    """Plain text: what a run looks like off a terminal."""

    styled = False

    def __init__(self, host: Host):
        self.host = host
        self._hinted = False

    @classmethod
    def for_host(cls, host: Host) -> "Ui":
        terminal = host.terminal()
        if terminal is None:
            return cls(host)
        return StyledUi(host, terminal, load(host))

    def intro(self) -> None:
        pass

    def text(self, text: str) -> None:
        self.host.show(text)

    def ask(self, message: str) -> str:
        return self.host.prompt(message)

    def section(self, title: str, description: str, progress: Progress | None = None) -> "Host":
        """Start a section; returns the host its checks run through."""
        if progress:
            self.host.show(progress.plain())
        return self.host

    def end_section(self) -> None:
        pass

    def result(self, text: str, outcome: str) -> None:
        self.host.show(text)

    def choose(self, header: str, options: Sequence[str], selected: Sequence[str]) -> list[str]:
        """Which options the human keeps. Off a terminal, the ones given (--skip decides)."""
        return list(selected)

    def human(self, question: str) -> tuple[str | None, str, bool]:
        """A human check's answer, "yes", "no" or "skip" (None: no answer at all), the note, and whether
        the answer was the default (a bare Enter: yes, but nobody typed it)."""
        if not self._hinted:
            self._hinted = True
            self.text(HUMAN_HINT)
        return self._human_by_prompt(question)

    def _prompt_text(self, text: str) -> str:
        """A prompt as it's shown (the styled UI wraps it into the text column)."""
        return text

    def _human_by_prompt(self, question: str) -> tuple[str | None, str, bool]:
        for _ in range(HUMAN_TRIES):
            try:
                typed = self._io().prompt(self._prompt_text(f"{question} [Y/n/s]") + " ").strip()
            except EOFError:
                return None, "", False
            if not typed:
                return "yes", "", True
            word, _, note = typed.partition(" ")
            if word.lower() in HUMAN_WORDS:
                return HUMAN_WORDS[word.lower()], note.strip(), False
            self.text("Please answer y, n or s (Enter alone is yes).")
        return None, "", False

    def _io(self) -> Host:
        """Where prompts go: the section's feed while one runs (it lifts itself), else the host."""
        return self.host

    def confirm(self, question: str, on_eof: bool = False) -> bool:
        """Go ahead with an action? Enter (or y) is yes, anything else no; end of input is `on_eof`."""
        try:
            answer = self._io().prompt(self._prompt_text(question + " [Y/n]") + " ").strip().lower()
        except EOFError:
            return on_eof
        return answer in ("", "y", "yes")

    def close(self) -> None:
        pass


class StyledUi(Ui):
    """Omarchy's installer look."""

    styled = True

    def __init__(self, host: Host, terminal: Terminal, theme: Theme):
        super().__init__(host)
        self.terminal = terminal
        self.theme = theme
        width = theme.logo_width if theme.logo and theme.logo_width <= terminal.width else 80
        self.left = max(0, (terminal.width - width) // 2)
        self.pad = " " * self.left
        # The text column: from the logo's left edge, the logo's width (at least 80), inside the terminal
        # with one column spare so a full line never makes the terminal wrap by itself.
        self.column = max(20, min(max(width, 80), terminal.width - self.left - 1))
        self.feed: Feed | None = None
        self._gum: bool | None = None

    # -- colour and layout ----------------------------------------------

    def paint(self, name: str, text: str) -> str:
        return f"{_rgb(self.theme.colour(name))}{text}{RESET}"

    def _padded(self, text: str) -> str:
        """`text` wrapped to the text column and lined up under the logo."""
        return "\n".join(self.pad + line if line else line for line in wrap(text, self.column))

    def _wrapped(self, text: str, less: int = 0) -> str:
        """`text` wrapped for gum, which pads it by itself: `less` narrower for gum's own prefix."""
        return "\n".join(wrap(text, max(20, self.column - less)))

    def _centred(self, block: str) -> str:
        lines = block.split("\n")
        width = max((len(line) for line in lines), default=0)
        left = " " * max(0, (self.terminal.width - width) // 2)
        return "\n".join(left + line for line in lines)

    # -- what the run shows -----------------------------------------------

    def intro(self) -> None:
        self.host.show(CLEAR_SCREEN)
        if self.theme.logo and self.theme.logo_width <= self.terminal.width:
            self.host.show("\n" + self.paint("green", self._centred(self.theme.logo)) + "\n")
        else:
            self.host.show("\n" + self.pad + BOLD + self.paint("green", TOOL_NAME) + "\n")
        caption = f"{TOOL_NAME} {TOOL_VERSION}: hardware test for Omarchy on Apple Silicon"
        self.host.show(self.paint("dark_foreground", self._centred(caption)) + "\n")

    def text(self, text: str) -> None:
        self._io().show(self.paint("foreground", self._padded(text)))

    def ask(self, message: str) -> str:
        return self._io().prompt(self._prompt_text(message.rstrip(" ")) + (" " if message.endswith(" ") else ""))

    def _io(self) -> Host:
        return self.feed if self.feed else self.host

    def section(self, title: str, description: str, progress: Progress | None = None) -> "Host":
        if progress:
            self.host.show("\n" + self.pad + self.progress_line(progress))
        self.host.show(("" if progress else "\n") + self.pad + BOLD + self.paint("accent", title))
        self.host.show(self.pad + self.paint("accent", RULE * min(self.column, max(len(title), 40))))
        self.host.show(self.paint("dark_foreground", self._padded(description)) + "\n")
        rows = max(FEED_MIN_ROWS, min(FEED_MAX_ROWS, self.terminal.height - 16 - (1 if progress else 0)))
        self.feed = Feed(self.host, self, rows, progress)
        return self.feed

    def progress_line(self, progress: Progress, width: int | None = None) -> str:
        """The bar in the theme's colours (done, this section, to come), then "Section 4/13 · Audio  31%"."""
        width = width or self.column
        label, percent = f"  {progress.label}", f"  {progress.percent}%"
        cells = min(PROGRESS_BAR_WIDTH * 2, width - len(label) - len(percent))
        if cells < 10:  # a narrow terminal: the words only, cut to fit (one row, or the feed's redraw drifts)
            return self.paint("foreground", (progress.label + percent)[:max(1, width)])
        done, current, rest = progress.cells(cells)
        bar = self.paint("green", "━" * done) + self.paint("accent", "━" * current) + self.paint("dark_foreground", "─" * rest)
        return bar + self.paint("foreground", label) + self.paint("dark_foreground", percent)

    def end_section(self) -> None:
        if self.feed:
            self.feed.close()
            self.feed = None

    def result(self, text: str, outcome: str) -> None:
        self.host.show(self.paint(OUTCOME_COLOURS.get(outcome, "dark_foreground"), self._padded(text)))

    # -- gum --------------------------------------------------------------

    def _has_gum(self) -> bool:
        if self._gum is None:
            self._gum = self.host.run(["gum", "--version"]).returncode == 0
        return self._gum

    def _gum_run(self, argv: list[str]) -> CommandResult:
        result = self._io().run_tty(argv, with_padding(self.theme, self.left))
        if result.returncode == 130:
            raise Interrupted
        return result

    def choose(self, header: str, options: Sequence[str], selected: Sequence[str]) -> list[str]:
        if not self._has_gum():
            return self._choose_by_prompt(options, selected)
        argv = ["gum", "choose", "--no-limit", "--header", self._wrapped(header)]
        if selected:
            argv += ["--selected", ",".join(selected) if len(selected) < len(options) else "*"]
        result = self._gum_run(argv + list(options))
        if result.returncode != 0:
            return list(selected)
        picked = {line.strip() for line in result.stdout.splitlines()}
        return [option for option in options if option in picked]

    def _choose_by_prompt(self, options: Sequence[str], selected: Sequence[str]) -> list[str]:
        try:
            answer = self._io().prompt(self._prompt_text("Sections to skip (numbers, e.g. 2 5; Enter runs them all):") + " ")
        except EOFError:
            return list(selected)
        skip = {int(n) - 1 for n in re.findall(r"\d+", answer)}
        return [option for i, option in enumerate(options) if option in selected and i not in skip]

    def _prompt_text(self, text: str) -> str:
        return self._padded(text)

    def confirm(self, question: str, on_eof: bool = False) -> bool:
        if not self._has_gum():
            return super().confirm(question, on_eof)
        # gum confirm: Yes is selected, so Enter goes ahead; y and n answer too, Esc is no.
        return self._gum_run(["gum", "confirm", self._wrapped(question + " [Y/n]")]).returncode == 0

    def close(self) -> None:
        self.end_section()
        self.host.show(SHOW_CURSOR + RESET)


def unlogged(host: Host) -> Host:
    """The host under a section's feed: what runs through it isn't shown (a poll repeated every second)."""
    if isinstance(host, Bounded):
        return Bounded(unlogged(host.inner))
    return host.inner if isinstance(host, Feed) else host


def note(host: Host, text: str) -> None:
    """A line of the section's feed that no command printed (nothing off a terminal)."""
    if isinstance(host, Bounded):
        host = host.inner
    if isinstance(host, Feed):
        host.note(text)


class Feed:
    """The live feed: a host that shows, as they happen, the commands a section runs and their output.

    Everything else passes straight through to the inner host. A prompt or
    message in the middle of a section lifts the feed, then draws it again
    below.
    """

    def __init__(self, inner: Host, ui: StyledUi, rows: int, progress: Progress | None = None):
        self.inner = inner
        self.ui = ui
        self.progress = progress
        self.lines: deque[str] = deque(maxlen=rows)
        self.rows = rows + (1 if progress else 0)  # the lines, then the progress line under them
        self.drawn = False
        self.width = max(20, ui.terminal.width - ui.left - len(FEED_PREFIX) - 1)
        self.inner.show(HIDE_CURSOR + ("\n" * (self.rows - 1)))
        self.drawn = True
        self._draw(up=True)

    # -- the machine, logged ------------------------------------------------

    def run(self, argv: Sequence[str]) -> CommandResult:
        self._add(["$ " + " ".join(argv)])
        result = self.inner.run(argv)
        self._add((result.stdout + result.stderr).splitlines())
        return result

    def run_bundled(self, name: str, args: Sequence[str] = ()) -> CommandResult:
        self._add(["$ " + " ".join([name, *args])])
        result = self.inner.run_bundled(name, args)  # type: ignore[attr-defined]
        self._add((result.stdout + result.stderr).splitlines())
        return result

    def read_file(self, path: str) -> bytes:
        self._add([f"read {path}"])
        return self.inner.read_file(path)

    def list_dir(self, path: str) -> list[str]:
        self._add([f"list {path}"])
        return self.inner.list_dir(path)

    def note(self, text: str) -> None:
        self._add([text])

    # -- the human, with the feed lifted -----------------------------------

    def show(self, text: str) -> None:
        self._lift()
        self.inner.show(text)
        self._reopen()

    def prompt(self, message: str) -> str:
        self._lift()
        try:
            return self.inner.prompt(message)
        finally:
            self._reopen()

    def run_tty(self, argv: Sequence[str], env: dict[str, str] | None = None) -> CommandResult:
        self._lift()
        try:
            return self.inner.run_tty(argv, env)
        finally:
            self._reopen()

    def __getattr__(self, name: str):
        return getattr(self.inner, name)

    # -- drawing ------------------------------------------------------------

    def _add(self, lines: Sequence[str]) -> None:
        added = False
        for line in lines:
            line = printable(line)
            if line.strip():
                # Wrapped under a two-space hang, at most a few rows: the rest of a long line is left out.
                rows = textwrap.wrap(line, self.width, subsequent_indent="  ", break_on_hyphens=False) or [line[: self.width]]
                if len(rows) > FEED_ROWS_PER_LINE:
                    rows = rows[:FEED_ROWS_PER_LINE]
                    rows[-1] = rows[-1][: self.width - 3] + "..."
                self.lines.extend(rows)
                added = True
        if added and self.drawn:
            self._draw(up=True)

    def _draw(self, up: bool) -> None:
        feed_rows = self.rows - (1 if self.progress else 0)
        shown = list(self.lines) + [""] * (feed_rows - len(self.lines))
        frame = "\n".join(
            CLEAR_LINE + (self.ui.paint("dark_foreground", f"{self.ui.pad}{FEED_PREFIX}{line}") if line else "")
            for line in shown
        )
        if self.progress:
            frame += "\n" + CLEAR_LINE + self.ui.pad + self.ui.progress_line(self.progress, self.ui.terminal.width - self.ui.left - 1)
        self.inner.show((f"{ESC}{self.rows}A\r" if up else "") + frame)

    def _lift(self) -> None:
        if self.drawn:
            self.inner.show(f"{ESC}{self.rows}A\r{CLEAR_BELOW}{SHOW_CURSOR}" + ESC + "1A")
            self.drawn = False

    def _reopen(self) -> None:
        if not self.drawn:
            self.inner.show(HIDE_CURSOR + ("\n" * (self.rows - 1)))
            self.drawn = True
            self._draw(up=True)

    def close(self) -> None:
        self._lift()
        self.lines.clear()
