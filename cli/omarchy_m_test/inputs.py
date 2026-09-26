"""The Input section's built-in keyboard and trackpad checks: the function keys and the trackpad's gestures.

Both are human checks: pressing a key or swiping is something only the
human can do. As evidence, Hyprland's device list says which built-in keyboard and trackpad
it sees: BUILT_IN_SCRIPT reads `hyprctl devices -j` on the Mac, once per run,
and prints only the built-in devices' driver names (apple-spi-keyboard,
apple-mtp-...), so the name of a keyboard or mouse someone plugged in or
paired never leaves it, not even into a recording. hid_apple's fnmode says
whether the top row sends F-keys or media keys first. Macs without a
built-in keyboard and trackpad (Mac mini, Mac Studio) don't ask.
"""

from __future__ import annotations

from . import human
from .session import Context

FUNCTION_KEYS = "input.function-keys"
GESTURES = "input.trackpad-gestures"
# Run as `sh -c SCRIPT`: "unavailable" when Hyprland can't be asked (over SSH), else one built-in device name a line.
BUILT_IN_SCRIPT = r"""out=$(hyprctl devices -j 2>/dev/null) || { echo unavailable; exit 0; }
printf '%s\n' "$out" | grep -oE '"name": *"apple-(spi|mtp|internal)-[^"]*"' | sed -E 's/^"name": *"(.*)"$/\1/' | sort -u"""
DEVICES = ["sh", "-c", BUILT_IN_SCRIPT]
DEVICES_CACHE = "hyprctl_devices"
FNMODE = "/sys/module/hid_apple/parameters/fnmode"
# The built-in keyboard and trackpad: SPI on M1 (and M2 Airs), MTP (DockChannel) on the M2 Pro and Max.
BUILT_IN_PREFIXES = ("apple-spi-", "apple-mtp-", "apple-internal-")
FNMODES = {
    "0": "0 (the top row sends F-keys only)",
    "1": "1 (media keys first, F-keys with Fn)",
    "2": "2 (F-keys first, media keys with Fn)",
    "3": "3 (auto: media keys first, F-keys with Fn)",
}

FUNCTION_KEYS_QUESTION = (
    "On the built-in keyboard, press the brightness keys (F1, F2) and the volume keys (F10, F11, F12), with Fn if they need it: "
    "did each do what its key shows?"
)
GESTURES_QUESTION = (
    "On the built-in trackpad, try a click, a tap, a two-finger click (right-click), two-finger scrolling both ways "
    "and a three-finger swipe between workspaces: did each work smoothly?"
)


def built_in(ctx: Context) -> list[str] | str:
    """The built-in input devices Hyprland lists; why not, when it can't list them."""
    if DEVICES_CACHE not in ctx.cache:
        listed = ctx.host.run(DEVICES)
        names = [line.strip() for line in listed.stdout.splitlines() if line.strip()]
        if listed.returncode != 0 or names == ["unavailable"]:
            ctx.cache[DEVICES_CACHE] = "Hyprland couldn't list the input devices (run from the desktop to see them)"
        else:
            ctx.cache[DEVICES_CACHE] = [name for name in names if name.startswith(BUILT_IN_PREFIXES)]
    return ctx.cache[DEVICES_CACHE]


def _seen(ctx: Context, word: str, match: tuple[str, ...]) -> str:
    known = built_in(ctx)
    if isinstance(known, str):
        return known
    names = [name for name in known if any(part in name for part in match)]
    return f"built-in {word} (Hyprland): {', '.join(names)}" if names else f"Hyprland lists no built-in {word}"


def fnmode(ctx: Context) -> str | None:
    try:
        value = ctx.host.read_file(FNMODE).decode("ascii", "replace").strip()
    except OSError:
        return None
    return f"hid_apple fnmode: {FNMODES.get(value, value)}"


def function_keys(ctx: Context) -> dict:
    if human.absent(ctx, FUNCTION_KEYS):
        return human.skip(FUNCTION_KEYS, "this Mac has no built-in keyboard")
    evidence = [_seen(ctx, "keyboard", ("keyboard",))]
    mode = fnmode(ctx)
    if mode:
        evidence.append(mode)
    return human.check(ctx, FUNCTION_KEYS, FUNCTION_KEYS_QUESTION, evidence)


def gestures(ctx: Context) -> dict:
    if human.absent(ctx, GESTURES):
        return human.skip(GESTURES, "this Mac has no built-in trackpad")
    evidence = [_seen(ctx, "trackpad", ("trackpad", "touch"))]
    return human.check(ctx, GESTURES, GESTURES_QUESTION, evidence)


def run(ctx: Context) -> list[dict]:
    return [function_keys(ctx), gestures(ctx)]
