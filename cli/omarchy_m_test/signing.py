"""Machine signing: every report is signed with this Mac's own key.

On its first run the CLI creates an ed25519 key under the state directory
($XDG_STATE_HOME/omarchy-m-test/machine-key, ~/.local/state/...), readable
only by this user, and reuses it on every later run. Nobody is asked anything
and the private half never leaves the Mac: a report carries only the public
key and a signature (see the "signature" object in schema/report-v1.schema.json).

The signature is ssh-keygen's (SSHSIG, namespace NAMESPACE) over the report's
canonical form: the report without its "signature" member, as JSON with keys
sorted, no whitespace and non-ASCII kept as UTF-8, exactly what
json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False) gives.
Reports have no floating-point numbers, so this form is the same in any
language; the site (site/app/models/machine_signature.rb) rebuilds it to verify.
"""

from __future__ import annotations

import json

from .host import Host, SigningError
from .session import state_dir

NAMESPACE = "omarchy-m-test-report"
KEY_NAME = "omarchy-m-test/machine-key"


def canonical(report: dict) -> bytes:
    """The bytes a report's signature covers."""
    unsigned = {name: value for name, value in report.items() if name != "signature"}
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def key_path(host: Host) -> str | None:
    base = state_dir(host)
    return f"{base}/{KEY_NAME}" if base else None


def sign(host: Host, report: dict) -> tuple[dict, str | None]:
    """The report with its signature, or the report as it was and why it couldn't be signed."""
    path = key_path(host)
    if path is None:
        return report, "there's no home directory to keep this Mac's key in"
    try:
        signed = host.machine_sign(path, NAMESPACE, canonical(report))
    except SigningError as problem:
        return report, str(problem)
    return {**report, "signature": {"public_key": signed.public_key, "signature": signed.signature}}, None
