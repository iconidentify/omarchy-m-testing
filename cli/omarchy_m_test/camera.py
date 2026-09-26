"""The Camera section: the ISP's camera device, a few frames from it, and the human's look at its picture.

Aurora adds the camera's image signal processor (apple-isp, the catalogue's
isp-camera). The section:

  - device (automatic): a V4L2 device (/sys/class/video4linux/video*) whose
    driver is apple-isp. DEVICES_SCRIPT prints each video device's node and
    driver only, never the name a USB webcam gives itself.
  - frames (automatic): ffmpeg reads FRAMES frames from it into the null
    muxer; it passes when they all arrive. The resolution and pixel format
    ffmpeg saw are the evidence. No frame is ever kept.
  - image (human): mpv shows the camera live in a window for PREVIEW_SECONDS,
    then the human says whether the picture was right. Only for someone at
    the Mac: a Wayland session, a local seat and no SSH (presence.py).

Macs without a built-in camera (Mac mini, Mac Studio: the catalogue says
absent) skip all three. ffmpeg and mpv come with Omarchy; where they're
missing the checks that need them are skipped, with the reason.
"""

from __future__ import annotations

import re

from . import human, presence
from .session import Context

DEVICE = "camera.isp"
FRAMES_CHECK = "camera.frames"
IMAGE = "camera.image"
CHECK_IDS = (DEVICE, FRAMES_CHECK, IMAGE)
DRIVER = "apple-isp"
FRAMES = 30
PREVIEW_SECONDS = 10
NOT_INSTALLED = 127
TIMED_OUT = 124  # timeout(1) ended it: the preview ran its full time

# Run as `sh -c SCRIPT`: "NODE DRIVER" per video device, e.g. "video0 apple-isp".
DEVICES_SCRIPT = (
    'for d in /sys/class/video4linux/video*; do [ -e "$d" ] || continue; '
    'drv=$(readlink "$d/device/driver"); echo "${d##*/} ${drv##*/}"; done'
)
DEVICES = ["sh", "-c", DEVICES_SCRIPT]

IMAGE_QUESTION = (
    "Did the camera window show you, live: the right way up, in focus, with natural colours and smooth movement?"
)

_STREAM = re.compile(r"Stream #\S+: Video: .*?, (\w+)(?:\([^)]*\))?, (\d+x\d+)")
_FRAME_COUNT = re.compile(r"frame=\s*(\d+)")


def frames_argv(node: str, frames: int = FRAMES) -> list[str]:
    return ["timeout", "20", "ffmpeg", "-hide_banner", "-nostdin", "-f", "v4l2", "-i", f"/dev/{node}",
            "-frames:v", str(frames), "-f", "null", "-"]


def preview_argv(node: str) -> list[str]:
    return ["timeout", str(PREVIEW_SECONDS), "mpv", "--really-quiet", "--no-config", "--title=omarchy-m-test camera",
            "--profile=low-latency", "--untimed", f"av://v4l2:/dev/{node}"]


def parse_devices(stdout: str) -> list[tuple[str, str]]:
    found = []
    for line in stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and re.fullmatch(r"video\d+", parts[0]):
            found.append((parts[0], parts[1]))
        elif len(parts) == 1 and re.fullmatch(r"video\d+", parts[0]):
            found.append((parts[0], "no driver"))
    return found


def device(ctx: Context) -> tuple[dict, str | None]:
    """The device check, and the ISP's video node when it has one."""
    listed = ctx.host.run(DEVICES)
    found = parse_devices(listed.stdout) if listed.returncode == 0 else []
    isp = next((node for node, driver in found if driver == DRIVER), None)
    others = [f"{node} ({driver})" for node, driver in found if node != isp]
    evidence = []
    if isp:
        evidence.append(f"camera: /dev/{isp}, from the ISP driver ({DRIVER})")
        status = "pass"
    else:
        evidence.append(f"no camera device from the ISP driver ({DRIVER})")
        status = "fail"
    if others:
        evidence.append("other video devices: " + ", ".join(others))
    return _automatic(DEVICE, status, evidence), isp


def frames(ctx: Context, node: str | None) -> dict:
    if node is None:
        return _automatic(FRAMES_CHECK, "skip", ["skipped: no camera device (see camera.isp)"])
    result = ctx.host.run(frames_argv(node))
    if result.returncode == NOT_INSTALLED:
        return _automatic(FRAMES_CHECK, "skip", ["skipped: ffmpeg isn't installed"])
    output = result.stderr + result.stdout
    counts = [int(count) for count in _FRAME_COUNT.findall(output)]
    got = counts[-1] if counts else 0
    stream = _STREAM.search(output)
    evidence = [f"asked ffmpeg for {FRAMES} frames from /dev/{node} (read and discarded, none kept)"]
    if stream:
        evidence.append(f"stream: {stream.group(2)}, {stream.group(1)}")
    if result.returncode == TIMED_OUT:
        evidence.append("timed out after 20 s")
    evidence.append(f"frames: {got} of {FRAMES}")
    if result.returncode != 0 and got < FRAMES:
        why = _why(result)
        if why:
            evidence.append(f"ffmpeg: {why}")
    return _automatic(FRAMES_CHECK, "pass" if got >= FRAMES else "fail", evidence)


def image(ctx: Context, node: str | None, captured: dict) -> dict:
    if node is None:
        return human.skip(IMAGE, "no camera device (see camera.isp)")
    if captured["status"] == "skip":
        return human.skip(IMAGE, "no frames were read (see camera.frames)")
    if captured["status"] != "pass":
        return human.skip(IMAGE, "the camera gave no frames (see camera.frames)")
    why = _blocked(ctx)
    if why:
        return human.skip(IMAGE, why)
    _say(ctx, f"A window shows the camera for {PREVIEW_SECONDS} seconds: look at it, and move a little.")
    shown = ctx.host.run(preview_argv(node))
    if shown.returncode == NOT_INSTALLED:
        return human.skip(IMAGE, "mpv isn't installed")
    if shown.returncode not in (0, TIMED_OUT):
        return human.skip(IMAGE, f"mpv couldn't show the camera ({_why(shown) or f'exit {shown.returncode}'})")
    return human.check(ctx, IMAGE, IMAGE_QUESTION, [f"showed /dev/{node} live for {PREVIEW_SECONDS} s (mpv)"])


def run(ctx: Context) -> list[dict]:
    if human.absent(ctx, DEVICE):
        return [
            _automatic(DEVICE, "skip", ["skipped: this Mac has no built-in camera"]),
            _automatic(FRAMES_CHECK, "skip", ["skipped: this Mac has no built-in camera"]),
            human.skip(IMAGE, "this Mac has no built-in camera"),
        ]
    found, node = device(ctx)
    captured = frames(ctx, node)
    return [found, captured, image(ctx, node, captured)]


def _blocked(ctx: Context) -> str | None:
    over_ssh = "running over SSH: the camera is shown on this Mac's own screen, for someone at it"
    if any(ctx.host.env(name) for name in presence.SSH_VARIABLES):
        return over_ssh
    if not ctx.host.env("WAYLAND_DISPLAY"):
        return "no Wayland desktop session to show the camera in"
    found = presence.of(ctx.host, ctx.cache)
    if found.ssh:
        return over_ssh
    if not found.seat:
        return f"no local desktop session ({found.why_no_seat})"
    return None


def _why(result) -> str:
    lines = [line.strip() for line in (result.stderr or result.stdout).splitlines() if line.strip()]
    return lines[-1][:200] if lines else ""


def _say(ctx: Context, text: str) -> None:
    if ctx.ui:
        ctx.ui.text(text)
    else:
        ctx.host.show(text)


def _automatic(check_id: str, status: str, evidence: list[str]) -> dict:
    return {"id": check_id, "kind": "automatic", "status": status, "evidence": evidence}
