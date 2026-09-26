"""Recorded hosts: replay what a real machine answered at the host boundary.

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
      "/proc/device-tree/compatible": null
    },
    "dirs": {"/proc/device-tree": ["compatible", "model"]}
  }

A file or directory mapped to null is recorded as absent (FileNotFoundError).
Anything the CLI asks for that the recording doesn't mention raises
RecordingMiss, so a test can never pass by silently reading this machine.

The human side is scripted: `answers` are returned by prompt() in order
(EOF ends input like Ctrl-D). Uploads get the scripted `responses` in order.
Everything shown, prompted, written and posted is kept for assertions.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any, Sequence

from .host import CommandResult, HttpResponse

RECORDING_VERSION = 1


class RecordingMiss(Exception):
    """The CLI asked for something the recording (or the script) doesn't have."""


class _Eof:
    def __repr__(self) -> str:
        return "EOF"


EOF = _Eof()


@dataclass(frozen=True)
class Post:
    url: str
    body: str


@dataclass
class RecordedHost:
    recording: dict[str, Any]
    answers: list[Any] = field(default_factory=list)
    responses: list[HttpResponse] = field(default_factory=list)
    # What happened, in order: ("show", text) / ("prompt", message, answer)
    transcript: list[tuple] = field(default_factory=list)
    commands_run: list[list[str]] = field(default_factory=list)
    written: dict[str, str] = field(default_factory=dict)
    posts: list[Post] = field(default_factory=list)

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
        files = self.recording.get("files", {})
        if path not in files:
            raise RecordingMiss(f"file not in recording: {path}")
        entry = files[path]
        if entry is None:
            raise FileNotFoundError(path)
        if "text" in entry:
            return entry["text"].encode("utf-8")
        return base64.b64decode(entry["base64"])

    def list_dir(self, path: str) -> list[str]:
        dirs = self.recording.get("dirs", {})
        if path not in dirs:
            raise RecordingMiss(f"directory not in recording: {path}")
        if dirs[path] is None:
            raise FileNotFoundError(path)
        return sorted(dirs[path])

    # -- human ---------------------------------------------------------

    def prompt(self, message: str) -> str:
        if not self.answers:
            raise RecordingMiss(f"no scripted answer left for prompt: {message!r}")
        answer = self.answers.pop(0)
        self.transcript.append(("prompt", message, answer))
        if answer is EOF:
            raise EOFError
        return answer

    def show(self, text: str) -> None:
        self.transcript.append(("show", text))

    # -- outputs -------------------------------------------------------

    def write_file(self, path: str, text: str) -> None:
        self.written[path] = text

    def post_json(self, url: str, body: str) -> HttpResponse:
        self.posts.append(Post(url, body))
        if not self.responses:
            raise RecordingMiss(f"no scripted response left for POST {url}")
        return self.responses.pop(0)

    # -- assertions helpers ---------------------------------------------

    @property
    def output(self) -> str:
        """Everything the human saw, prompts included, as one text."""
        parts = []
        for event in self.transcript:
            parts.append(event[1])
        return "\n".join(parts)

    def unused_script(self) -> list[Any]:
        return self.answers + self.responses
