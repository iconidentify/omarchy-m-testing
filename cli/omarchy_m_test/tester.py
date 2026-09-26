"""Tester sign-in: `omarchy-m-test --sign-in`, once per Mac.

GitHub's device flow, with only the OAuth app's client ID (no secret ever
ships in the tool): GitHub gives a short code, the tester enters it at
github.com/login/device, and the CLI polls until GitHub hands it a token.
The CLI then sends the site that token in a sign-in signed with this Mac's
machine key (signing.py, namespace NAMESPACE). The site asks GitHub whose
token it is, checks this app issued it, binds that GitHub handle to the
machine key and revokes the token. The token is never written anywhere.

From then on every report this Mac signs counts as a tester run while the
handle is on the site's tester allowlist; nothing else changes in a run.
"""

from __future__ import annotations

import json

from .host import Host, HttpResponse, NetworkError
from .signing import sign_document

# The omarchy-m-testing OAuth app (owned by the site's owner), device flow enabled.
GITHUB_CLIENT_ID = "Ov23liyct9clXDWu2d42"
DEVICE_CODE_URL = "https://github.com/login/device/code"
TOKEN_URL = "https://github.com/login/oauth/access_token"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
BINDING_PATH = "/api/v1/tester_bindings"
NAMESPACE = "omarchy-m-test-tester"
BINDING_VERSION = 1
# GitHub's defaults, when its answer leaves them out.
DEFAULT_INTERVAL = 5
DEFAULT_EXPIRES_IN = 900
SLOW_DOWN_SECONDS = 5

EXIT_OK = 0
EXIT_FAILED = 5


class SignInFailed(Exception):
    """Why the sign-in stopped, in words for the tester."""


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


def _poll(host: Host, device: dict) -> str:
    """Wait for the tester to enter the code; the token GitHub hands back."""
    interval = _number(device.get("interval"), DEFAULT_INTERVAL)
    left = _number(device.get("expires_in"), DEFAULT_EXPIRES_IN)
    fields = {"client_id": GITHUB_CLIENT_ID, "device_code": device["device_code"], "grant_type": DEVICE_GRANT}
    while left > 0:
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


def sign_in(host: Host, site: str) -> int:
    """Sign this Mac in as a tester on `site`; the exit status."""
    try:
        device = _device_code(host)
        host.show(
            "Tester sign-in with GitHub.\n"
            f"Open {device['verification_uri']} (on any device) and enter this code:\n\n"
            f"    {device['user_code']}\n\n"
            "Waiting for GitHub... (Ctrl-C cancels)"
        )
        token = _poll(host, device)
        bound = _bind(host, site, token)
    except SignInFailed as failed:
        host.show(f"Sign-in failed: {failed}. Nothing changed; run omarchy-m-test --sign-in to try again.")
        return EXIT_FAILED
    except KeyboardInterrupt:
        host.show("\nSign-in cancelled. Nothing changed.")
        return EXIT_FAILED
    login = bound["login"]
    if bound.get("tester"):
        host.show(f"Signed in as @{login}. From now on this Mac's runs count as tester runs; there's nothing else to do.")
    else:
        host.show(
            f"Signed in as @{login}, but @{login} isn't on the tester allowlist yet. "
            "Once the site's admin adds it, this Mac's runs count as tester runs."
        )
    return EXIT_OK
