"""Tester sign-in: `omarchy-m-test --sign-in`, once per Mac, or when a run offers it.

GitHub's device flow, with only the OAuth app's client ID (no secret ever
ships in the tool): GitHub gives a short code, the tester enters it at
github.com/login/device, and the CLI polls until GitHub hands it a token.
The CLI then sends the site that token in a sign-in signed with this Mac's
machine key (signing.py, namespace NAMESPACE). The site asks GitHub whose
token it is, checks this app issued it, binds that GitHub handle to the
machine key and revokes the token. The token is never written anywhere.

From then on every report this Mac signs counts as a tester run while the
handle is on the site's tester allowlist; nothing else changes in a run.

The Mac remembers the sign-in in the state directory (LINK_NAME: the handle
and whether it's a tester, never a token). A run (not --dry-run or --record)
whose Mac has no such record first asks the site whether this machine key is
signed in already (a Mac signed in before the record existed), and otherwise
offers, once per Mac, to sign in (OFFER_QUESTION). When the site can't be
asked, the run isn't offered it; a later run is. A "no", a skip, a timeout
or a failure is remembered too, so the offer never comes back; --sign-in
still works any time. While the offer waits for the code, a countdown runs
for up to OFFER_WAIT_SECONDS and any key skips it: the run goes on unsigned.

`--status` and `--sign-out` send the site a small request signed with the
machine key (namespace NAMESPACE, dated requested_at; a sign-out names the
sign-in it ends, which the status gives, so a copy of it can't end a later one): the site says whose handle the key is bound to, or unbinds
it. Signing out removes the record, so the next run offers the sign-in again.
Runs already uploaded keep the handle they were uploaded under.
"""

from __future__ import annotations

import json

from typing import Callable

from .host import Host, HttpResponse, NetworkError
from .session import state_dir
from .signing import sign_document

# The omarchy-m-testing OAuth app (owned by the site's owner), device flow enabled.
GITHUB_CLIENT_ID = "Ov23liyct9clXDWu2d42"
DEVICE_CODE_URL = "https://github.com/login/device/code"
TOKEN_URL = "https://github.com/login/oauth/access_token"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
BINDING_PATH = "/api/v1/tester_bindings"
NAMESPACE = "omarchy-m-test-tester"
BINDING_VERSION = 1
# --status, --sign-out: {"request_version", "request": "status"|"sign-out", "requested_at": seconds, "signature"}.
REQUEST_PATH = "/api/v1/tester_requests"
REQUEST_VERSION = 1
STATUS, SIGN_OUT = "status", "sign-out"
# Where this Mac remembers the sign-in, or that the offer was answered: {"link_version", "login", "tester"} or
# {"link_version", "declined": true}. In the state directory, next to the machine key.
LINK_NAME = "omarchy-m-test/tester.json"
LINK_VERSION = 1
OFFER_QUESTION = "Sign in with GitHub so your runs count as a tester?"
OFFER_WAIT_SECONDS = 300
# GitHub's defaults, when its answer leaves them out.
DEFAULT_INTERVAL = 5
DEFAULT_EXPIRES_IN = 900
SLOW_DOWN_SECONDS = 5

EXIT_OK = 0
EXIT_FAILED = 5


class SignInFailed(Exception):
    """Why the sign-in stopped, in words for the tester."""


def _reason(failed: SignInFailed) -> str:
    """The reason as part of a sentence (the site's own errors end with a full stop)."""
    return str(failed).rstrip(".")


class SignInSkipped(Exception):
    """The human pressed a key while the offered sign-in waited for the code."""


Wait = Callable[[int], None]  # waits `interval` seconds between polls; raises to stop waiting


class Countdown:
    """The offered sign-in's wait: second by second with the time left shown, up to `budget` seconds by the
    clock from its start (GitHub's answers count too); any key skips (SignInSkipped), running out stops it
    (SignInFailed)."""

    def __init__(self, host: Host, budget: int = OFFER_WAIT_SECONDS):
        self.host = host
        self.budget = budget
        self.deadline = host.now() + budget

    def __call__(self, interval: int) -> None:
        until = self.host.now() + interval
        while (now := self.host.now()) < until:
            left = self.deadline - now
            if left <= 0:
                raise SignInFailed(f"no code was entered within {self.budget // 60} minutes")
            minutes, seconds = divmod(left, 60)
            if self.host.wait_key(1, f"  Waiting for GitHub: {minutes}:{seconds:02d} left. Press any key to skip.") is not None:
                raise SignInSkipped


def _json(response: HttpResponse) -> dict:
    try:
        body = json.loads(response.body)
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _github(host: Host, url: str, fields: dict[str, str]) -> dict:
    try:
        response = host.post_form(url, fields)
    except NetworkError as error:
        raise SignInFailed(f"couldn't reach GitHub ({error})") from error
    body = _json(response)
    if response.status != 200 and not body.get("error"):
        raise SignInFailed(f"GitHub answered HTTP {response.status}")
    return body


def _device_code(host: Host) -> dict:
    body = _github(host, DEVICE_CODE_URL, {"client_id": GITHUB_CLIENT_ID, "scope": ""})
    if body.get("error"):
        raise SignInFailed(f"GitHub refused to start the sign-in ({body.get('error_description') or body['error']})")
    if not all(isinstance(body.get(name), str) and body[name] for name in ("device_code", "user_code", "verification_uri")):
        raise SignInFailed("GitHub's answer didn't have a sign-in code")
    return body


def _number(value, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else default


def _poll(host: Host, device: dict, wait: Wait | None = None) -> str:
    """Wait for the tester to enter the code; the token GitHub hands back."""
    interval = _number(device.get("interval"), DEFAULT_INTERVAL)
    left = _number(device.get("expires_in"), DEFAULT_EXPIRES_IN)
    fields = {"client_id": GITHUB_CLIENT_ID, "device_code": device["device_code"], "grant_type": DEVICE_GRANT}
    while left > 0:
        if wait:
            wait(interval)
        else:
            host.sleep(interval)
        left -= interval
        body = _github(host, TOKEN_URL, fields)
        token = body.get("access_token")
        if isinstance(token, str) and token:
            return token
        error = body.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval = _number(body.get("interval"), interval + SLOW_DOWN_SECONDS)
            continue
        if error == "access_denied":
            raise SignInFailed("the sign-in was cancelled on GitHub")
        if error == "expired_token":
            break
        raise SignInFailed(f"GitHub refused the sign-in ({body.get('error_description') or error or 'no token'})")
    raise SignInFailed("the code expired before it was entered")


def _bind(host: Host, site: str, token: str) -> dict:
    signed, unsigned_because = sign_document(host, {"binding_version": BINDING_VERSION, "github_token": token}, NAMESPACE)
    if unsigned_because:
        raise SignInFailed(f"this Mac's key can't sign the sign-in: {unsigned_because}")
    try:
        response = host.post_json(site + BINDING_PATH, json.dumps(signed, ensure_ascii=False))
    except NetworkError as error:
        raise SignInFailed(f"couldn't reach {site} ({error})") from error
    body = _json(response)
    if response.status == 201 and isinstance(body.get("login"), str):
        return body
    raise SignInFailed(body.get("error") or f"{site} answered HTTP {response.status}")


def _link_path(host: Host) -> str | None:
    base = state_dir(host)
    return f"{base}/{LINK_NAME}" if base else None


def read_link(host: Host) -> dict | None:
    """What this Mac remembers of the sign-in: {"login", "tester"}, {"declined": True}, or None."""
    path = _link_path(host)
    if path is None:
        return None
    try:
        link = json.loads(host.read_file(path))
    except (OSError, ValueError):
        return None
    return link if isinstance(link, dict) and link.get("link_version") == LINK_VERSION else None


def _remember(host: Host, **link) -> None:
    path = _link_path(host)
    if path:
        host.write_file(path, json.dumps({"link_version": LINK_VERSION, **link}, sort_keys=True) + "\n", private=True)


def _forget(host: Host) -> None:
    path = _link_path(host)
    if path:
        host.remove_file(path)


def _request(host: Host, site: str, request: str, **fields: str) -> dict:
    """The site's answer to a signed status or sign-out request: {"signed_in", "login", "tester", "sign_in", ...}."""
    document = {"request_version": REQUEST_VERSION, "request": request, "requested_at": host.now(), **fields}
    signed, unsigned_because = sign_document(host, document, NAMESPACE)
    if unsigned_because:
        raise SignInFailed(f"this Mac's key can't sign the request: {unsigned_because}")
    try:
        response = host.post_json(site + REQUEST_PATH, json.dumps(signed, ensure_ascii=False))
    except NetworkError as error:
        raise SignInFailed(f"couldn't reach {site} ({error})") from error
    body = _json(response)
    if response.status == 200 and isinstance(body.get("signed_in"), bool):
        if body["signed_in"] and not isinstance(body.get("login"), str):
            raise SignInFailed(f"{site}'s answer didn't name the handle")
        return body
    raise SignInFailed(body.get("error") or f"{site} answered HTTP {response.status}")


def signed_in_line(login: str, is_tester: bool) -> str:
    if is_tester:
        return f"Signed in as @{login} (tester: yes). This Mac's runs count as tester runs."
    return f"Signed in as @{login} (tester: no): ask the maintainer to add you as a tester."


def _bound_line(bound: dict) -> str:
    login = bound["login"]
    if bound.get("tester"):
        return f"Signed in as @{login}. From now on this Mac's runs count as tester runs; there's nothing else to do."
    return (f"Signed in as @{login}, but @{login} isn't on the tester allowlist yet: ask the maintainer to add you as a tester. "
            "Once they do, this Mac's runs count as tester runs.")


def _sign_in(host: Host, site: str, say: Callable[[str], None], waiting: str, wait: Wait | None = None) -> dict:
    device = _device_code(host)
    say(
        "Tester sign-in with GitHub.\n"
        f"Open {device['verification_uri']} (on any device) and enter this code:\n\n"
        f"    {device['user_code']}\n\n"
        + waiting
    )
    bound = _bind(host, site, _poll(host, device, wait))
    _remember(host, login=bound["login"], tester=bool(bound.get("tester")))
    return bound


def sign_in(host: Host, site: str) -> int:
    """Sign this Mac in as a tester on `site`; the exit status."""
    try:
        bound = _sign_in(host, site, host.show, "Waiting for GitHub... (Ctrl-C cancels)")
    except SignInFailed as failed:
        host.show(f"Sign-in failed: {_reason(failed)}. Nothing changed; run omarchy-m-test --sign-in to try again.")
        return EXIT_FAILED
    except KeyboardInterrupt:
        host.show("\nSign-in cancelled. Nothing changed.")
        return EXIT_FAILED
    host.show(_bound_line(bound))
    return EXIT_OK


def offer(host: Host, say: Callable[[str], None], confirm: Callable[[str], bool], site: str) -> None:
    """At the start of a run: sign this Mac in if the human wants to, once per Mac. Never stops the run."""
    if _link_path(host) is None or read_link(host) is not None:
        return
    try:
        known = _request(host, site, STATUS)
    except SignInFailed:
        return  # the site can't say whether this Mac is signed in already (an older CLI's sign-in): offer on a later run
    if known["signed_in"]:
        _remember(host, login=known["login"], tester=bool(known.get("tester")))
        say(signed_in_line(known["login"], bool(known.get("tester"))))
        return
    if not confirm(OFFER_QUESTION):
        _remember(host, declined=True)
        say("Not signing in: this run is a community run. omarchy-m-test --sign-in signs this Mac in any time.")
        return
    waiting = f"Waiting up to {OFFER_WAIT_SECONDS // 60} minutes; press any key to skip and run without signing in."
    try:
        bound = _sign_in(host, site, say, waiting, Countdown(host))
    except SignInSkipped:
        _remember(host, declined=True)
        say("Skipped signing in: this run is a community run. omarchy-m-test --sign-in signs this Mac in any time.")
        return
    except SignInFailed as failed:
        _remember(host, declined=True)
        say(f"Couldn't sign in ({_reason(failed)}): carrying on as a community run. omarchy-m-test --sign-in tries again any time.")
        return
    say(_bound_line(bound))


def status(host: Host, site: str) -> int:
    """omarchy-m-test --status: whose handle this Mac is signed in as, as the site knows it."""
    try:
        known = _request(host, site, STATUS)
    except SignInFailed as failed:
        link = read_link(host) or {}
        if isinstance(link.get("login"), str):
            host.show(f"This Mac was signed in as @{link['login']} when it last checked; couldn't check with the site now: {_reason(failed)}.")
        else:
            host.show(f"Couldn't check the sign-in with the site: {_reason(failed)}.")
        return EXIT_FAILED
    if known["signed_in"]:
        _remember(host, login=known["login"], tester=bool(known.get("tester")))
        host.show(signed_in_line(known["login"], bool(known.get("tester"))))
    else:
        if isinstance((read_link(host) or {}).get("login"), str):
            _forget(host)  # unbound on the site (the admin, or another sign-out): the next run offers the sign-in again
        host.show("Not signed in. omarchy-m-test --sign-in signs this Mac in as a tester.")
    return EXIT_OK


def sign_out(host: Host, site: str) -> int:
    """omarchy-m-test --sign-out: unbind this Mac's key from its handle on the site and forget the sign-in.
    The sign-out names the sign-in it ends (the status says which), so a copy of it can't end a later one."""
    try:
        known = _request(host, site, STATUS)
        if not known["signed_in"]:
            _forget(host)
            host.show("This Mac wasn't signed in. The next run offers to sign in.")
            return EXIT_OK
        if not isinstance(known.get("sign_in"), str):
            raise SignInFailed(f"{site}'s answer didn't say which sign-in to end")
        answer = _request(host, site, SIGN_OUT, sign_in=known["sign_in"])
    except SignInFailed as failed:
        host.show(f"Sign-out failed: {_reason(failed)}. Nothing changed; run omarchy-m-test --sign-out to try again.")
        return EXIT_FAILED
    _forget(host)
    login = answer.get("signed_out") or known["login"]
    host.show(f"Signed out @{login}: this Mac's runs no longer count as tester runs (runs already uploaded keep theirs). "
              "The next run offers to sign in again.")
    return EXIT_OK
