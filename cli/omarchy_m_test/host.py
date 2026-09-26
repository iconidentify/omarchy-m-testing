"""The host boundary: the CLI's only seam.

Every interaction with the machine, the human and the network goes through a
Host. Nothing else in the package may import subprocess, open files, read
input, print or open network connections (scripts/check_boundary.py enforces
this). Tests swap RealHost for a RecordedHost (see recording.py) that replays
what a real Mac answered.

Operations:
  run(argv)                  run a command (no shell), capture its output
  read_file(path)            read a file's bytes; FileNotFoundError if absent
  list_dir(path)             list a directory's entry names, sorted
  prompt(message)            ask the human; returns the typed line; EOFError on end of input
  show(text)                 show text to the human
  write_file(path, text)     write a file the CLI produces (the report)
  post_json(url, body)       POST a JSON text body; returns the HTTP response
"""

from __future__ import annotations

import os
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol, Sequence

COMMAND_TIMEOUT_SECONDS = 60
HTTP_TIMEOUT_SECONDS = 30


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: str


class NetworkError(Exception):
    """The request never got an HTTP response (DNS, TLS, refused, timeout)."""


class Host(Protocol):
    def run(self, argv: Sequence[str]) -> CommandResult: ...

    def read_file(self, path: str) -> bytes: ...

    def list_dir(self, path: str) -> list[str]: ...

    def prompt(self, message: str) -> str: ...

    def show(self, text: str) -> None: ...

    def write_file(self, path: str, text: str) -> None: ...

    def post_json(self, url: str, body: str) -> HttpResponse: ...


class RealHost:
    """The host backed by this machine, its terminal and the network."""

    def run(self, argv: Sequence[str]) -> CommandResult:
        try:
            done = subprocess.run(
                list(argv),
                capture_output=True,
                text=True,
                errors="replace",
                timeout=COMMAND_TIMEOUT_SECONDS,
                stdin=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            return CommandResult(127, "", f"{argv[0]}: command not found\n")
        except subprocess.TimeoutExpired:
            return CommandResult(124, "", f"{argv[0]}: timed out after {COMMAND_TIMEOUT_SECONDS}s\n")
        return CommandResult(done.returncode, done.stdout, done.stderr)

    def read_file(self, path: str) -> bytes:
        with open(path, "rb") as f:
            return f.read()

    def list_dir(self, path: str) -> list[str]:
        return sorted(os.listdir(path))

    def prompt(self, message: str) -> str:
        return input(message)

    def show(self, text: str) -> None:
        print(text)
        sys.stdout.flush()

    def write_file(self, path: str, text: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def post_json(self, url: str, body: str) -> HttpResponse:
        request = urllib.request.Request(
            url,
            data=body.encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                return HttpResponse(response.status, response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as error:
            return HttpResponse(error.code, error.read().decode("utf-8", "replace"))
        except (urllib.error.URLError, OSError) as error:
            raise NetworkError(str(getattr(error, "reason", error))) from error
