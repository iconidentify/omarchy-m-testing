"""Recordings: capture what a real machine answers at the host boundary, and replay it.

A recording is a JSON file (recording_version 1):

  {
    "recording_version": 1,
    "description": "what machine and install this is",
    "source": "where the answers came from",
    "commands": [
      {"argv": ["uname", "-r"], "returncode": 0, "stdout": "...\\n", "stderr": ""}
    ],
    "files": {
      "/proc/device-tree/model": {"text": "Apple ...\\u0000"},
      "/some/binary": {"base64": "..."},
      "/some/redacted/binary": {"redacted_bytes": 6},
      "/proc/device-tree/compatible": null
    },
    "dirs": {"/proc/device-tree": ["compatible", "model"]},
    "env": {"HOME": "/home/<user>"}
  }

A file or directory mapped to null is recorded as absent (FileNotFoundError).
A binary file the recorder could not scrub is kept only as its size and
replays as that many zero bytes. An environment variable the recording
doesn't list is unset; "env" is only saved when a run read one that was set.

Record mode (`omarchy-m-test --record FILE`) wraps the real host in a
RecordingHost: every command, file and directory the CLI asks for is kept,
plus the RECORDED_SOURCES that later checks need (kernel log, device tree,
first-boot, Wi-Fi and lid journals, PCI and input devices). Before the
recording is written it passes the privacy Scrubber (privacy.py), so no
hostname, username, network name or address is ever saved. Prompts, what the
human typed and uploads are not recorded.

Replay: a RecordedHost answers from a recording. Anything the CLI asks for
that the recording doesn't mention raises RecordingMiss, so a test can never
pass by silently reading this machine. The human side is scripted: `answers`
are returned by prompt() in order (EOF ends input like Ctrl-D). Uploads get
the scripted `responses` in order. GETs (the latest-release lookup) get
the scripted `fetches` by URL; a URL that isn't scripted behaves like a
machine with no network (NetworkError). The answer INTERRUPT at a prompt or an
interactive command is Ctrl-C there (KeyboardInterrupt). Interactive commands
(run_tty, gum) also take their scripted result from `answers`: a
CommandResult, a string (its stdout, exit 0), EOF or INTERRUPT. The host is
not at a terminal unless the test gives one (`terminal`). A file the CLI wrote
reads back what it wrote, until it removes it. Everything shown, prompted,
written and posted is kept for assertions.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any, Sequence

from .host import CommandResult, Host, HttpResponse, NetworkError, Terminal
from .privacy import HOME_DIR, HOSTNAME_PATH, Scrubber

RECORDING_VERSION = 1

# What record mode captures beyond what the CLI itself asks for, so that
# recordings from real Macs carry the evidence later checks read.
RECORDED_SOURCES: tuple[list[str], ...] = (
    ["journalctl", "--dmesg", "--boot=0", "--no-pager"],
    ["dtc", "-I", "fs", "-O", "dts", "/proc/device-tree"],
    ["journalctl", "--unit=omarchy-provision-hardware.service", "--output=short-iso", "--no-pager"],
    ["journalctl", "--boot=0", "--unit=NetworkManager.service", "--unit=iwd.service", "--output=short-precise", "--no-pager"],
    ["journalctl", "--boot=0", "--unit=systemd-logind.service", "--no-pager"],
    ["uname", "-a"],
    ["lspci", "-nn"],
    ["hyprctl", "devices", "-j"],
    ["ip", "-brief", "address"],
)

# Binary files whose content may be kept: none yet. A check that reads a
# binary it produced itself (a screenshot of a test card) adds its prefix.
RECORDABLE_BINARY_PREFIXES: tuple[str, ...] = ()


class RecordingMiss(Exception):
    """The CLI asked for something the recording (or the script) doesn't have."""


class _Eof:
    def __repr__(self) -> str:
        return "EOF"


EOF = _Eof()


class _Interrupt:
    def __repr__(self) -> str:
        return "INTERRUPT"


INTERRUPT = _Interrupt()


@dataclass(frozen=True)
class Post:
    url: str
    body: str


@dataclass
class RecordedHost:
    recording: dict[str, Any]
    answers: list[Any] = field(default_factory=list)
    responses: list[HttpResponse] = field(default_factory=list)
    fetches: dict[str, HttpResponse] = field(default_factory=dict)
    terminal_size: Terminal | None = None
    # What happened, in order: ("show", text) / ("prompt", message, answer) / ("tty", argv, answer)
    transcript: list[tuple] = field(default_factory=list)
    commands_run: list[list[str]] = field(default_factory=list)
    written: dict[str, str] = field(default_factory=dict)
    posts: list[Post] = field(default_factory=list)
    gets: list[str] = field(default_factory=list)
    removed: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        version = self.recording.get("recording_version")
        if version != RECORDING_VERSION:
            raise ValueError(f"unsupported recording_version {version!r}")
        self.answers = list(self.answers)
        self.responses = list(self.responses)

    @classmethod
    def load(cls, path: str, **kwargs: Any) -> "RecordedHost":
        with open(path, encoding="utf-8") as f:  # test harness: reads the recording, not the host
            return cls(json.load(f), **kwargs)

    # -- machine -------------------------------------------------------

    def run(self, argv: Sequence[str]) -> CommandResult:
        argv = list(argv)
        self.commands_run.append(argv)
        for entry in self.recording.get("commands", []):
            if entry["argv"] == argv:
                return CommandResult(entry["returncode"], entry.get("stdout", ""), entry.get("stderr", ""))
        raise RecordingMiss(f"command not in recording: {argv}")

    def read_file(self, path: str) -> bytes:
        if path in self.written:
            return self.written[path].encode("utf-8")
        if path in self.removed:
            raise FileNotFoundError(path)
        files = self.recording.get("files", {})
        if path not in files:
            raise RecordingMiss(f"file not in recording: {path}")
        entry = files[path]
        if entry is None:
            raise FileNotFoundError(path)
        if "text" in entry:
            return entry["text"].encode("utf-8")
        if "redacted_bytes" in entry:
            return bytes(entry["redacted_bytes"])
        return base64.b64decode(entry["base64"])

    def list_dir(self, path: str) -> list[str]:
        dirs = self.recording.get("dirs", {})
        if path not in dirs:
            raise RecordingMiss(f"directory not in recording: {path}")
        if dirs[path] is None:
            raise FileNotFoundError(path)
        return sorted(dirs[path])

    def env(self, name: str) -> str | None:
        return self.recording.get("env", {}).get(name)

    # -- human ---------------------------------------------------------

    def terminal(self) -> Terminal | None:
        return self.terminal_size

    def prompt(self, message: str) -> str:
        if not self.answers:
            raise RecordingMiss(f"no scripted answer left for prompt: {message!r}")
        answer = self.answers.pop(0)
        self.transcript.append(("prompt", message, answer))
        if answer is EOF:
            raise EOFError
        if answer is INTERRUPT:
            raise KeyboardInterrupt
        return answer

    def run_tty(self, argv: Sequence[str], env: dict[str, str] | None = None) -> CommandResult:
        if not self.answers:
            raise RecordingMiss(f"no scripted answer left for interactive command: {list(argv)}")
        answer = self.answers.pop(0)
        self.transcript.append(("tty", list(argv), answer))
        if answer is INTERRUPT:
            raise KeyboardInterrupt
        if answer is EOF:
            return CommandResult(130, "", "")
        if isinstance(answer, str):
            return CommandResult(0, answer + "\n" if answer else "", "")
        return answer

    def show(self, text: str) -> None:
        self.transcript.append(("show", text))

    # -- outputs -------------------------------------------------------

    def write_file(self, path: str, text: str) -> None:
        self.written[path] = text
        self.removed.discard(path)

    def remove_file(self, path: str) -> None:
        self.written.pop(path, None)
        self.removed.add(path)

    def post_json(self, url: str, body: str) -> HttpResponse:
        self.posts.append(Post(url, body))
        if not self.responses:
            raise RecordingMiss(f"no scripted response left for POST {url}")
        return self.responses.pop(0)

    def get(self, url: str) -> HttpResponse:
        self.gets.append(url)
        if url not in self.fetches:
            raise NetworkError(f"no network in this recording: GET {url}")
        return self.fetches[url]

    # -- assertions helpers ---------------------------------------------

    @property
    def output(self) -> str:
        """Everything the human saw, prompts included, as one text."""
        return "\n".join(event[1] for event in self.transcript if isinstance(event[1], str))

    def unused_script(self) -> list[Any]:
        return self.answers + self.responses


class RecordingHost:
    """Record mode: a host that passes everything to `inner` and keeps what the machine answered."""

    def __init__(self, inner: Host):
        self.inner = inner
        self.commands: list[dict[str, Any]] = []
        self.files: dict[str, Any] = {}
        self.dirs: dict[str, Any] = {}
        self.env_read: dict[str, str | None] = {}

    # -- machine (recorded) ---------------------------------------------

    def run(self, argv: Sequence[str]) -> CommandResult:
        argv = list(argv)
        result = self.inner.run(argv)
        if not any(entry["argv"] == argv for entry in self.commands):
            self.commands.append({"argv": argv, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
        return result

    def read_file(self, path: str) -> bytes:
        try:
            data = self.inner.read_file(path)
        except FileNotFoundError:
            self.files.setdefault(path, None)
            raise
        self.files.setdefault(path, data)
        return data

    def list_dir(self, path: str) -> list[str]:
        try:
            names = self.inner.list_dir(path)
        except FileNotFoundError:
            self.dirs.setdefault(path, None)
            raise
        self.dirs.setdefault(path, list(names))
        return names

    def env(self, name: str) -> str | None:
        value = self.inner.env(name)
        self.env_read.setdefault(name, value)
        return value

    # -- human and outputs (passed through, not recorded) -----------------

    def terminal(self) -> Terminal | None:
        return self.inner.terminal()

    def prompt(self, message: str) -> str:
        return self.inner.prompt(message)

    def run_tty(self, argv: Sequence[str], env: dict[str, str] | None = None) -> CommandResult:
        return self.inner.run_tty(argv, env)

    def remove_file(self, path: str) -> None:
        self.inner.remove_file(path)

    def show(self, text: str) -> None:
        self.inner.show(text)

    def write_file(self, path: str, text: str) -> None:
        self.inner.write_file(path, text)

    def post_json(self, url: str, body: str) -> HttpResponse:
        return self.inner.post_json(url, body)

    def get(self, url: str) -> HttpResponse:
        return self.inner.get(url)

    # -- saving ------------------------------------------------------------

    def capture_sources(self, sources: Sequence[Sequence[str]] = RECORDED_SOURCES) -> None:
        """Run each extra source so the recording carries its answer."""
        for argv in sources:
            try:
                self.run(argv)
            except RecordingMiss:
                continue  # recording from a recording that doesn't have this source

    def recording(self, scrubber: Scrubber) -> dict[str, Any]:
        """The scrubbed recording of everything captured so far."""
        recording = {
            "recording_version": RECORDING_VERSION,
            "description": "Recorded by omarchy-m-test --record",
            "source": "omarchy-m-test --record",
            "commands": [
                {
                    "argv": [scrubber.scrub(arg) for arg in entry["argv"]],
                    "returncode": entry["returncode"],
                    "stdout": scrubber.scrub(entry["stdout"]),
                    "stderr": scrubber.scrub(entry["stderr"]),
                }
                for entry in self.commands
            ],
            "files": {scrubber.scrub(path): _file_entry(path, data, scrubber) for path, data in self.files.items()},
            "dirs": {scrubber.scrub(path): _dir_entry(path, names, scrubber) for path, names in self.dirs.items()},
        }
        env = {name: scrubber.scrub(value) for name, value in self.env_read.items() if value is not None}
        if env:
            recording["env"] = env
        return recording

    def save(self, path: str, learn: bool = True) -> None:
        """Scrub what was captured, then write it through the inner host.

        With learn, the scrubber also learns this machine's hostname, accounts
        and saved networks (reading them through this recorder); without it,
        only its patterns apply.
        """
        scrubber = Scrubber.for_host(self) if learn else Scrubber()
        self.inner.write_file(path, json.dumps(self.recording(scrubber), indent=2, ensure_ascii=False) + "\n")


def _dir_entry(path: str, names: list[str] | None, scrubber: Scrubber) -> list[str] | None:
    if names is None:
        return None
    if path == HOME_DIR:  # account names, however short
        return ["<user>" if not name.startswith(".") else name for name in sorted(names)]
    return sorted(scrubber.scrub(name) for name in names)


def _file_entry(path: str, data: bytes | None, scrubber: Scrubber) -> dict[str, Any] | None:
    if data is None:
        return None
    if path == HOSTNAME_PATH:  # the hostname, however short
        return {"text": "<hostname>\n"}
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        if path.startswith(RECORDABLE_BINARY_PREFIXES):
            return {"base64": base64.b64encode(data).decode("ascii")}
        return {"redacted_bytes": len(data)}
    return {"text": scrubber.scrub(text)}
