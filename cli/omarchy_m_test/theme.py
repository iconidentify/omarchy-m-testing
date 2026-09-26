"""The look of a run: the installed Omarchy logo, the user's theme colours and gum styling.

Everything is read through the host, only when the human is at a terminal:

- The logo: logo.txt in $OMARCHY_PATH, else /usr/share/omarchy (the
  omarchy-mac package) or ~/.local/share/omarchy (a git install).
- The colours: the current theme's colors.toml,
  ~/.local/state/omarchy/current/theme/ (older installs:
  ~/.config/omarchy/current/theme/), resolved by `omarchy-theme-color --all`
  exactly as Omarchy's own templates resolve it. Without that command the
  file is read here, and a theme with no colors.toml yet gives its
  alacritty.toml colours.
- Section titles: `omarchy-ascii TITLE`, the logo's own font (Delta Corps
  Priest 1), when it is installed and the title fits.
- gum: Omarchy's installer styling (presentation.sh) for any GUM_* the
  user's environment doesn't already set.

Another Asahi distro has none of these: the run uses Tokyo Night, Omarchy's
default theme, with a plain title instead of the logo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .host import Host

OMARCHY_DIRS = ("/usr/share/omarchy", "{home}/.local/share/omarchy")
THEME_DIRS = ("{home}/.local/state/omarchy/current/theme", "{home}/.config/omarchy/current/theme")
THEME_COLOR = "omarchy-theme-color"
ASCII = "omarchy-ascii"

# Omarchy's tokyo-night colors.toml.
TOKYO_NIGHT = {
    "accent": "#7aa2f7",
    "muted": "#414868",
    "background": "#1a1b26",
    "foreground": "#a9b1d6",
    "dark_foreground": "#565f89",
    "bright_foreground": "#c0caf5",
    "red": "#f7768e",
    "yellow": "#e0af68",
    "green": "#9ece6a",
    "cyan": "#449dab",
    "blue": "#7aa2f7",
    "magenta": "#ad8ee6",
}

# Old themes name their palette by ANSI slot only.
_ANSI_NAMES = {
    "color0": "background", "color1": "red", "color2": "green", "color3": "yellow",
    "color4": "blue", "color5": "magenta", "color6": "cyan", "color7": "foreground", "color8": "muted",
}
_ALACRITTY_NAMES = {"black": "background", "white": "foreground", "red": "red", "green": "green",
                    "yellow": "yellow", "blue": "blue", "magenta": "magenta", "cyan": "cyan"}
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
_TOML_LINE = re.compile(r"""^\s*([A-Za-z0-9_-]+)\s*=\s*["']?(#[0-9A-Fa-f]{6})["']?""")
_TOML_TABLE = re.compile(r"^\s*\[([^\]]+)\]")

# omarchy-mac's install/helpers/presentation.sh, in ANSI slots (the terminal
# already wears the theme) ...
_GUM_OMARCHY = {
    "GUM_CONFIRM_PROMPT_FOREGROUND": "6",
    "GUM_CONFIRM_SELECTED_FOREGROUND": "0",
    "GUM_CONFIRM_SELECTED_BACKGROUND": "2",
    "GUM_CONFIRM_UNSELECTED_FOREGROUND": "7",
    "GUM_CONFIRM_UNSELECTED_BACKGROUND": "0",
    "GUM_CHOOSE_HEADER_FOREGROUND": "6",
    "GUM_CHOOSE_CURSOR_FOREGROUND": "2",
    "GUM_CHOOSE_SELECTED_FOREGROUND": "2",
}
# ... and in Tokyo Night hex where the terminal may wear anything.
_GUM_TOKYO_NIGHT = {
    key: {"0": TOKYO_NIGHT["background"], "2": TOKYO_NIGHT["green"], "6": TOKYO_NIGHT["cyan"], "7": TOKYO_NIGHT["foreground"]}[value]
    for key, value in _GUM_OMARCHY.items()
}
_GUM_PADDED = ("GUM_CHOOSE_PADDING", "GUM_CONFIRM_PADDING", "GUM_INPUT_PADDING")


@dataclass(frozen=True)
class Theme:
    colours: dict[str, str]
    logo: str | None = None
    omarchy: bool = False           # colours came from the user's Omarchy theme
    has_ascii: bool = False
    gum_env: dict[str, str] = field(default_factory=dict)

    def colour(self, name: str) -> str:
        return self.colours.get(name) or TOKYO_NIGHT.get(name) or TOKYO_NIGHT["foreground"]

    @property
    def logo_width(self) -> int:
        return max((len(line) for line in (self.logo or "").splitlines()), default=0)


def load(host: Host) -> Theme:
    home = host.env("HOME") or ""
    logo = _logo(host, home)
    colours = _theme_colours(host, home)
    omarchy = colours is not None
    has_ascii = host.run([ASCII, "--help"]).returncode == 0
    gum = _GUM_OMARCHY if omarchy else _GUM_TOKYO_NIGHT
    gum_env = {key: value for key, value in gum.items() if host.env(key) is None}
    return Theme(_complete(colours), logo, omarchy, has_ascii, gum_env)


def _complete(colours: dict[str, str] | None) -> dict[str, str]:
    """Every colour the UI uses. A theme's missing ones come from its own palette, not Tokyo Night's."""
    if not colours:
        return dict(TOKYO_NIGHT)
    derived = dict(colours)
    derived.setdefault("accent", derived.get("blue", TOKYO_NIGHT["accent"]))
    derived.setdefault("dark_foreground", derived.get("muted", TOKYO_NIGHT["dark_foreground"]))
    derived.setdefault("bright_foreground", derived.get("foreground", TOKYO_NIGHT["bright_foreground"]))
    return {**TOKYO_NIGHT, **derived}


def with_padding(theme: Theme, left: int) -> dict[str, str]:
    """The gum environment with every prompt lined up with the logo, unless the user set their own."""
    env = dict(theme.gum_env)
    for key in _GUM_PADDED:
        env.setdefault(key, f"0 0 0 {left}")
    return env


def _read(host: Host, path: str) -> str | None:
    try:
        return host.read_file(path).decode("utf-8", "replace")
    except OSError:
        return None


def _logo(host: Host, home: str) -> str | None:
    configured = host.env("OMARCHY_PATH")
    dirs = [configured] if configured else [d.format(home=home) for d in OMARCHY_DIRS if home or "{home}" not in d]
    for directory in dirs:
        text = _read(host, f"{directory}/logo.txt")
        if text and text.strip():
            return text.rstrip("\n")
    return None


def _theme_colours(host: Host, home: str) -> dict[str, str] | None:
    if not home:
        return None
    for directory in (d.format(home=home) for d in THEME_DIRS):
        path = f"{directory}/colors.toml"
        text = _read(host, path)
        if text is not None:
            resolved = host.run([THEME_COLOR, "--file", path, "--all"])
            if resolved.returncode == 0:
                colours = _pairs(resolved.stdout)
            else:
                colours = _colors_toml(text)
            if colours:
                return colours
        text = _read(host, f"{directory}/alacritty.toml")
        if text is not None:
            colours = _alacritty(text)
            if colours:
                return colours
    return None


def _pairs(text: str) -> dict[str, str]:
    colours = {}
    for line in text.splitlines():
        key, _, value = line.partition("\t")
        if _HEX.match(value.strip()):
            colours[key.strip()] = value.strip()
    return colours


def _colors_toml(text: str) -> dict[str, str]:
    raw = {}
    for line in text.splitlines():
        match = _TOML_LINE.match(line)
        if match:
            raw[match.group(1)] = match.group(2)
    colours = {_ANSI_NAMES[key]: value for key, value in raw.items() if key in _ANSI_NAMES}
    colours.update({key: value for key, value in raw.items() if key not in _ANSI_NAMES})
    colours.setdefault("magenta", raw.get("purple", colours.get("magenta", "")))
    return {key: value for key, value in colours.items() if value}


def _alacritty(text: str) -> dict[str, str]:
    colours: dict[str, str] = {}
    table = ""
    for line in text.splitlines():
        header = _TOML_TABLE.match(line)
        if header:
            table = header.group(1).strip()
            continue
        match = _TOML_LINE.match(line)
        if not match:
            continue
        key, value = match.groups()
        if table == "colors.primary" and key in ("background", "foreground"):
            colours[key] = value
        elif table == "colors.normal" and key in _ALACRITTY_NAMES:
            colours.setdefault(_ALACRITTY_NAMES[key], value)
        elif table == "colors.bright" and key == "black":
            colours["muted"] = value
    return colours
