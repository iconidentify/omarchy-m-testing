"""The Input section's built-in keyboard and trackpad checks: the function keys and the trackpad's gestures.

Both are human checks: pressing a key or swiping is something only the
human can do. As evidence, Hyprland's device list says which built-in keyboard and trackpad
it sees: BUILT_IN_SCRIPT reads `hyprctl devices -j` on the Mac, once per run,
and prints only the built-in devices' driver names (apple-spi-keyboard,
apple-mtp-...), so the name of a keyboard or mouse someone plugged in or
paired never leaves it, not even into a recording. hid_apple's fnmode says
whether the top row sends F-keys or media keys first. Macs without a
built-in keyboard and trackpad (Mac mini, Mac Studio) don't ask.

The trackpad is asked one gesture at a time: a click, a two-finger click
(right-click), two-finger scrolling and a three-finger swipe between
workspaces. The swipe is only asked when the Hyprland config turns it on
(GESTURE_CONFIG_SCRIPT: Hyprland's live workspace_swipe option when it has
it, then the uncommented gesture lines of Omarchy's defaults and the
user's ~/.config/hypr, the later file winning). Omarchy leaves the
three-finger swipe commented out, so on a default install it is "skipped:
off in your config", never a failure. Tapping (tap-to-click, two-finger
tap, tap-and-drag) isn't a feature Omarchy offers on the Mac and is never
asked. Only on/off facts leave the script.
"""

from __future__ import annotations

from dataclasses import dataclass

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
CLICK, TWO_FINGER_CLICK, SCROLL, SWIPE = "click", "two-finger click", "two-finger scroll", "three-finger swipe"
GESTURE_QUESTIONS = {
    CLICK: "On the built-in trackpad, press down to click: did it click?",
    TWO_FINGER_CLICK: "Click with two fingers: did it right-click (a menu, where there is one)?",
    SCROLL: "Scroll with two fingers, up and down: did it scroll smoothly both ways?",
    SWIPE: "Swipe three fingers left and right: did it switch workspaces?",
}
OFF_IN_CONFIG = "off in your config"
# Run as `sh -c SCRIPT`: "swipe-live N" (older Hyprland's live gestures:workspace_swipe, when it has it), then
# from each config file in order, uncommented statements only (a file is flattened and split at each hl. call
# and gesture/workspace_swipe line, so multi-line blocks count): "gesture 3 DIRECTION ACTION" for a
# three-finger gesture (ACTION workspace, unset or other: never a command), "workspace-swipe 1|0"; last
# "files N", the config files read.
GESTURE_CONFIG_SCRIPT = r"""swipe=$(hyprctl getoption gestures:workspace_swipe 2>/dev/null | sed -n 's/^int: *//p')
[ -n "$swipe" ] && echo "swipe-live $swipe"
field() { printf '%s\n' "$1" | sed -nE "s/.*$2=\"?([A-Za-z0-9_-]+)\"?([,;}].*)?$/\1/p"; }
n=0
for f in "$HOME"/.local/share/omarchy/default/hypr/*.lua "$HOME"/.local/share/omarchy/default/hypr/*.conf \
         "$HOME"/.config/hypr/*.lua "$HOME"/.config/hypr/*.conf; do
  [ -r "$f" ] || continue
  n=$((n + 1))
  { sed -e 's/--.*$//' -e 's/#.*$//' "$f" | tr -d ' \t' | tr '\n' ';'; echo; } |
    sed -e 's/^/;/' -e 's/hl\./\nhl./g' -e 's/;gesture=/\ngesture=/g' -e 's/;workspace_swipe=/\nworkspace_swipe=/g' |
    while IFS= read -r c; do
      case $c in
        'hl.gesture({'*)
          c=${c%%\}*}
          [ "$(field "$c" fingers)" = 3 ] || continue
          action=$(printf '%s\n' "$c" | sed -nE 's/.*action="([a-z]+)"([,;].*)?$/\1/p')
          case $action in workspace|unset) ;; *) action=other;; esac
          echo "gesture 3 $(field "$c" direction) $action";;
        'gesture=3,'*)
          c=${c#gesture=}; c=${c%%;*}
          old=$IFS; IFS=,; set -- $c; IFS=$old
          dir=$2; shift 2; action=other
          for a in "$@"; do case $a in *:*) ;; workspace|unset) action=$a; break;; *) break;; esac; done
          echo "gesture 3 $dir $action";;
        'workspace_swipe='*)
          case ${c#workspace_swipe=} in true*|1*|yes*|on*) echo "workspace-swipe 1";; *) echo "workspace-swipe 0";; esac;;
      esac
    done
done
echo "files $n"
"""
GESTURE_CONFIG = ["sh", "-c", GESTURE_CONFIG_SCRIPT]


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


@dataclass(frozen=True)
class GestureConfig:
    swipe: bool | None  # a three-finger workspace swipe; None: couldn't tell


def parse_gesture_config(stdout: str) -> GestureConfig:
    """What GESTURE_CONFIG_SCRIPT found: a later statement overrides an earlier one (a three-finger gesture per
    direction, as Hyprland's unset matches it), a live option the config."""
    old_swipe: bool | None = None
    swipe_live: bool | None = None
    actions: dict[str, str] = {}  # three-finger gestures: direction => its last action
    files = 0
    for line in stdout.splitlines():
        words = line.split()
        if len(words) == 2 and words[0] == "swipe-live" and words[1] in ("0", "1"):
            swipe_live = words[1] == "1"
        elif len(words) == 2 and words[0] == "workspace-swipe":
            old_swipe = words[1] == "1"
        elif len(words) == 4 and words[:2] == ["gesture", "3"]:
            if words[3] == "unset":
                actions.pop(words[2], None)
            else:
                actions[words[2]] = words[3]
        elif len(words) == 2 and words[0] == "files" and words[1].isdigit():
            files = int(words[1])
    swipe: bool | None = "workspace" in actions.values() or bool(old_swipe)
    if swipe_live is not None:
        swipe = swipe_live
    elif not swipe and not files:
        swipe = None  # no config read: can't tell
    return GestureConfig(swipe)


def gesture_config(ctx: Context) -> GestureConfig:
    return parse_gesture_config(ctx.host.run(GESTURE_CONFIG).stdout)


def gestures(ctx: Context) -> dict:
    if human.absent(ctx, GESTURES):
        return human.skip(GESTURES, "this Mac has no built-in trackpad")
    evidence = [_seen(ctx, "trackpad", ("trackpad", "touch"))]
    config = gesture_config(ctx)
    evidence.append("Hyprland config: three-finger workspace swipe " + {True: "on", False: "off", None: "unknown"}[config.swipe])
    enabled = {CLICK: True, TWO_FINGER_CLICK: True, SCROLL: True, SWIPE: config.swipe is not False}
    parts = [(name, GESTURE_QUESTIONS[name] if enabled[name] else None, OFF_IN_CONFIG) for name in GESTURE_QUESTIONS]
    return human.check_each(ctx, GESTURES, parts, evidence)


def run(ctx: Context) -> list[dict]:
    return [function_keys(ctx), gestures(ctx)]
