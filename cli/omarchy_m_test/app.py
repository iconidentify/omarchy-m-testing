"""The whole CLI run: refuse non-Apple machines, disclaimer, checks, report, upload."""

from __future__ import annotations

import argparse
import json
from typing import Sequence

from . import TOOL_NAME, TOOL_VERSION, checks, report
from .catalogue import CatalogueError
from .consent import ACCEPT_PROMPT, DISCLAIMER, accepted
from .explain import explain, line, load_catalogue
from .host import Host, NetworkError
from .machine import NotAppleSilicon, identify

DEFAULT_SITE = "https://omarchy-m-testing.org"
DEFAULT_OUTPUT = "omarchy-m-test-report.json"
UPLOAD_PATH = "/api/v1/reports"

EXIT_OK = 0
EXIT_CANCELLED = 1
EXIT_REFUSED = 2
EXIT_UPLOAD_FAILED = 3
EXIT_BAD_INPUT = 4


class _Exit(Exception):
    def __init__(self, status: int):
        self.status = status


class _Parser(argparse.ArgumentParser):
    """argparse, but its help and errors go through the host."""

    def __init__(self, host: Host, **kwargs):
        self._host = host
        super().__init__(**kwargs)

    def _print_message(self, message, file=None):
        if message:
            self._host.show(message.rstrip("\n"))

    def exit(self, status=0, message=None):
        if message:
            self._host.show(message.rstrip("\n"))
        raise _Exit(status)


def _parse(argv: Sequence[str], host: Host) -> argparse.Namespace:
    parser = _Parser(host, prog=TOOL_NAME, description="Test this Mac's hardware under Omarchy.")
    parser.add_argument("--dry-run", action="store_true", help="run and write the report, but never upload it")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help=f"where to write the report (default: {DEFAULT_OUTPUT})")
    parser.add_argument("--site", default=DEFAULT_SITE, help=f"site to upload to (default: {DEFAULT_SITE})")
    parser.add_argument("--catalogue", metavar="FILE", help="use this feature catalogue instead of the bundled one (for trying a catalogue change)")
    parser.add_argument("--explain", metavar="REPORT", help="explain a saved report's results against the catalogue; runs no checks")
    parser.add_argument("--version", action="version", version=f"{TOOL_NAME} {TOOL_VERSION}")
    return parser.parse_args(list(argv))


def main(argv: Sequence[str], host: Host) -> int:
    try:
        args = _parse(argv, host)
    except _Exit as done:
        return done.status

    try:
        catalogue = load_catalogue(host, args.catalogue)
    except CatalogueError as problem:
        host.show(f"The feature catalogue {args.catalogue or '(bundled)'} can't be used: {problem}. Nothing was run.")
        return EXIT_BAD_INPUT

    if args.explain:
        return EXIT_OK if explain(host, args.explain, catalogue) else EXIT_BAD_INPUT

    try:
        machine = identify(host)
    except NotAppleSilicon as reason:
        host.show(
            f"{TOOL_NAME} only runs on Apple Silicon Macs running Linux, "
            f"and this machine isn't one ({reason}). Nothing was run."
        )
        return EXIT_REFUSED

    host.show(DISCLAIMER)
    try:
        answer = host.prompt(ACCEPT_PROMPT)
    except EOFError:
        answer = None
    if answer is None or not accepted(answer):
        host.show("Cancelled. Nothing was run.")
        return EXIT_CANCELLED

    host.show(f"Checking {machine.model}...")
    built = report.build(machine, [checks.system_identity(machine)], catalogue)
    for result in built["checks"]:
        host.show(line(result, result["classification"], catalogue))

    text = report.to_text(built)
    host.write_file(args.output, text)
    host.show(f"\nReport written to {args.output}. This is exactly what would be uploaded:\n")
    host.show(text)

    if args.dry_run:
        host.show("Dry run: the report was not uploaded.")
        return EXIT_OK

    site = args.site.rstrip("/")
    try:
        answer = host.prompt(f"Upload this report to {site}? [y/N] ")
    except EOFError:
        answer = ""
    if answer.strip().lower() not in ("y", "yes"):
        host.show(f"Not uploaded. The report is saved at {args.output}.")
        return EXIT_OK

    return _upload(host, site, text)


def _upload(host: Host, site: str, text: str) -> int:
    try:
        response = host.post_json(site + UPLOAD_PATH, text)
    except NetworkError as error:
        host.show(f"Upload failed: couldn't reach {site} ({error}). The report is saved locally.")
        return EXIT_UPLOAD_FAILED

    try:
        body = json.loads(response.body)
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}

    if response.status == 201 and body.get("report_url") and body.get("deletion_url"):
        host.show(f"Uploaded. Your report: {body['report_url']}")
        host.show(f"Keep this link to delete it later: {body['deletion_url']}")
        return EXIT_OK

    message = body.get("error") or f"the site answered HTTP {response.status}"
    host.show(f"Upload failed: {message}")
    details = body.get("details")
    for detail in details[:10] if isinstance(details, list) else []:
        host.show(f"  - {detail}")
    return EXIT_UPLOAD_FAILED
