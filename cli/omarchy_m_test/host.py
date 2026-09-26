"""The host boundary: the CLI's only seam.

Every interaction with the machine, the human and the network goes through a
Host. Nothing else in the package may import subprocess, open files, read
input, print or open network connections (scripts/check_boundary.py enforces
this). Tests swap RealHost for a RecordedHost (see recording.py) that replays
what a real Mac answered.

Operations:
  run(argv)                  run a command (no shell), capture its output
  run_bundled(name, args)    run one of the tool's own bundled scripts (bundled.py),
                             e.g. omarchy-mac's mac-check; recorded as bundled_argv()
  read_file(path)            read a file's bytes; FileNotFoundError if absent
  list_dir(path)             list a directory's entry names, sorted
  prompt(message)            ask the human; returns the typed line; EOFError on end of input
  show(text)                 show text to the human
  write_file(path, text, private=False)
                             write a file the CLI produces (the report); private: only this
                             user can read it (0600, in a 0700 directory: the checkpoint)
  post_json(url, body)       POST a JSON text body; returns the HTTP response
  get(url)                   GET a small text (the latest release's version); NetworkError if unreachable
  env(name)                  an environment variable's value; None when unset
  terminal()                 the terminal's size when the human is at one (stdin and stdout
                             a TTY), else None: output is then plain text, no colours or redraws
  run_tty(argv, env)         run an interactive command on the terminal (gum): it draws on
                             the terminal and reads keys; only its stdout is captured
  remove_file(path)          remove a file the CLI wrote itself (the checkpoint); no error if absent
"""

from __future__ import annotations

import http.client
import os
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol, Sequence

from . import bundled

COMMAND_TIMEOUT_SECONDS = 60
# Bundled check scripts run many commands (mac-check's boot check rebuilds and
# compares the m1n1 image), so they get longer.
BUNDLED_TIMEOUT_SECONDS = 300
HTTP_TIMEOUT_SECONDS = 30
# GETs only look up the latest release; a slow or absent network must not hold up a run.
GET_TIMEOUT_SECONDS = 5
BUNDLED_PREFIX = "bundled:"


def bundled_argv(name: str, args: Sequence[str] = ()) -> list[str]:
    """How a bundled script's run appears in a recording: ["bundled:mac-check", *args]."""
    return [BUNDLED_PREFIX + name, *args]


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class Terminal:
    width: int
    height: int


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: str


class NetworkError(Exception):
    """The request never got an HTTP response (DNS, TLS, refused, timeout)."""


class Host(Protocol):
    def run(self, argv: Sequence[str]) -> CommandResult: ...

    def run_bundled(self, name: str, args: Sequence[str] = ()) -> CommandResult: ...

    def read_file(self, path: str) -> bytes: ...

    def list_dir(self, path: str) -> list[str]: ...

    def prompt(self, message: str) -> str: ...

    def show(self, text: str) -> None: ...

    def write_file(self, path: str, text: str, private: bool = False) -> None: ...

    def post_json(self, url: str, body: str) -> HttpResponse: ...

    def get(self, url: str) -> HttpResponse: ...

    def env(self, name: str) -> str | None: ...

    def terminal(self) -> Terminal | None: ...

    def run_tty(self, argv: Sequence[str], env: dict[str, str] | None = None) -> CommandResult: ...

    def remove_file(self, path: str) -> None: ...


class RealHost:
    """The host backed by this machine, its terminal and the network."""

    def run(self, argv: Sequence[str]) -> CommandResult:
        return self._run(list(argv), COMMAND_TIMEOUT_SECONDS)

    def run_bundled(self, name: str, args: Sequence[str] = ()) -> CommandResult:
        try:
            path = bundled.script_path(name)
        except FileNotFoundError as missing:
            return CommandResult(127, "", f"{missing}\n")
        return self._run(["bash", path, *args], BUNDLED_TIMEOUT_SECONDS, name)

    def _run(self, argv: list[str], timeout: int, name: str | None = None) -> CommandResult:
        name = name or argv[0]
        try:
            done = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=timeout,
                stdin=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            return CommandResult(127, "", f"{name}: command not found\n")
        except subprocess.TimeoutExpired:
            return CommandResult(124, "", f"{name}: timed out after {timeout}s\n")
        return CommandResult(done.returncode, done.stdout, done.stderr)

    def read_file(self, path: str) -> bytes:
        with open(path, "rb") as f:
            return f.read()

    def list_dir(self, path: str) -> list[str]:
        return sorted(os.listdir(path))

    def prompt(self, message: str) -> str:
        return input(message)

    def show(self, text: str) -> None:
        try:
            print(text)
            sys.stdout.flush()
        except OSError:
            pass  # the terminal is gone (closed window, broken pipe); restoring must still go on

    def write_file(self, path: str, text: str, private: bool = False) -> None:
        """Write whole or not at all: a checkpoint cut short by a crash must not be half a file."""
        if os.path.exists(path) and not os.path.isfile(path):  # /dev/stdout, a FIFO
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            return
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, mode=0o700 if private else 0o777, exist_ok=True)
            if private:
                os.chmod(directory, 0o700)
        partial = path + ".partial"
        if os.path.lexists(partial):
            os.remove(partial)
        fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600 if private else 0o666)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(partial, path)

    def remove_file(self, path: str) -> None:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass

    def env(self, name: str) -> str | None:
        return os.environ.get(name)

    def terminal(self) -> Terminal | None:
        if os.environ.get("TERM") == "dumb" or not (sys.stdin.isatty() and sys.stdout.isatty()):
            return None
        try:
            size = os.get_terminal_size(sys.stdout.fileno())
        except OSError:
            return None
        return Terminal(size.columns, size.lines)

    def run_tty(self, argv: Sequence[str], env: dict[str, str] | None = None) -> CommandResult:
        try:
            done = subprocess.run(list(argv), stdout=subprocess.PIPE, text=True, errors="replace", env={**os.environ, **(env or {})})
        except FileNotFoundError:
            return CommandResult(127, "", f"{argv[0]}: command not found\n")
        return CommandResult(done.returncode, done.stdout, "")

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
        except (urllib.error.URLError, OSError, http.client.HTTPException) as error:
            raise NetworkError(str(getattr(error, "reason", error))) from error

    def get(self, url: str) -> HttpResponse:
        request = urllib.request.Request(url, headers={"Accept": "text/plain"})
        try:
            with urllib.request.urlopen(request, timeout=GET_TIMEOUT_SECONDS) as response:
                return HttpResponse(response.status, response.read(4096).decode("utf-8", "replace"))
        except urllib.error.HTTPError as error:
            return HttpResponse(error.code, "")
        except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException) as error:
            raise NetworkError(str(getattr(error, "reason", error))) from error
