"""Read monitor intent without executing user configuration (hyprlang and Omarchy's Lua).

Follow static sources in order. A named rule wins over the fallback; the
last rule for a selector wins. Computed monitor rules cannot be interpreted
safely here, so they leave the native-mode check skipped rather than failed.
"""

from __future__ import annotations

import fnmatch
import posixpath
import re
from dataclasses import dataclass

from .host import Host


@dataclass(frozen=True)
class Rule:
    output: str
    mode: str = "preferred"
    disabled: bool = False
    mirror: str = ""

    def matches(self, name: str, description: str) -> bool:
        return description.startswith(self.output[5:]) if self.output.startswith("desc:") else self.output == name


@dataclass
class Rules:
    entries: list[Rule]
    unavailable: bool = False

    def for_output(self, name: str, description: str) -> Rule:
        named = [rule for rule in self.entries if rule.output and rule.matches(name, description)]
        fallback = [rule for rule in self.entries if not rule.output]
        return (named or fallback or [Rule(name)])[-1]


def intent(host: Host, outputs: list[dict]) -> dict[str, dict]:
    """Only policy flags leave the host, never config text or description selectors."""
    rules = read(host)
    found = {}
    for output in outputs:
        name = output["name"]
        rule = rules.for_output(name, output.get("description", ""))
        found[name] = {"preferred": rule.mode == "preferred", "disabled": rule.disabled,
                       "mirrored": bool(rule.mirror or any(r.mirror == name for r in rules.entries)),
                       "unavailable": rules.unavailable}
    return found


def read(host: Host) -> Rules:
    home = host.env("HOME") or ""
    config = host.env("XDG_CONFIG_HOME") or f"{home}/.config"
    omarchy = host.env("OMARCHY_PATH") or "/usr/share/omarchy"
    roots = (config, omarchy, f"{home}/.local/share/omarchy")
    variables = {"HOME": home, "XDG_CONFIG_HOME": config}
    rules = Rules([])
    active: set[str] = set()
    reads = 0

    def expand(value: str) -> str:
        value = re.sub(r"\$(?:\{(\w+)\}|(\w+))", lambda m: variables.get(m[1] or m[2], m[0]), value)
        return home + value[1:] if value.startswith("~/") else value

    def load(path: str, optional: bool = False) -> bool:
        nonlocal reads
        path = posixpath.normpath(path)
        if path in active or reads >= 64:
            rules.unavailable = True
            return False
        try:
            text = host.read_file(path).decode("utf-8")
        except (OSError, UnicodeError):
            if not optional:
                rules.unavailable = True
            return False
        reads += 1
        active.add(path)
        lua = path.endswith(".lua")
        text = re.sub(r"--\[\[.*?\]\]", "", text, flags=re.S) if lua else text
        comment = r"--[^\n]*" if lua else r"#[^\n]*"
        text = re.sub(r'''("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|''' + comment,
                      lambda m: m[1] or "", text)
        pattern = (r"hl\.monitor\s*\(?\s*\{([^{}]*)\}|require\s*\(?\s*['\"]([^'\"]+)['\"]\s*\)?"
                   if lua else r"monitorv2\s*\{([^{}]*)\}|^\s*(monitor|source|\$\w+)\s*=\s*([^\n]+)")
        matches = list(re.finditer(pattern, text, re.M))
        if lua and len(re.findall(r"hl\.monitor\b", text)) != sum(m[1] is not None for m in matches):
            rules.unavailable = True
        if lua and "hl.monitor" in text and re.search(r"\b(if|for|while|function)\b", text):
            rules.unavailable = True
        if lua and re.search(r"\bdofile\b", text) and "/default/hypr/bootstrap.lua" not in text:
            rules.unavailable = True
        for match in matches:
            if lua:
                if match[2] is not None:
                    relative = match[2].replace(".", "/") + ".lua"
                    if not any(load(f"{root}/{relative}", optional=True) for root in roots):
                        rules.unavailable = True
                else:
                    rule = _table(match[1], lua=True)
                    if rule is None:
                        rules.unavailable = True
                    else:
                        rules.entries.append(rule)
            elif match[1] is not None:
                rule = _table(match[1], lua=False)
                if rule is None:
                    rules.unavailable = True
                else:
                    rules.entries.append(rule)
            else:
                key, value = match[2], expand(match[3].strip())
                if key.startswith("$"):
                    variables[key[1:]] = value
                elif key == "source":
                    value = value.strip('"\'')
                    if "$" in value:
                        rules.unavailable = True
                        continue
                    if not value.startswith("/"):
                        value = posixpath.join(posixpath.dirname(path), value)
                    sources = _sources(host, value)
                    if not sources:
                        rules.unavailable = True
                    for source in sources:
                        load(source)
                else:
                    fields = [field.strip() for field in value.split(",")]
                    if len(fields) < 2 or "$" in value:
                        rules.unavailable = True
                        continue
                    output, mode = fields[:2]
                    if mode in ("transform", "addreserved"):
                        continue
                    mirror = fields[fields.index("mirror") + 1] if "mirror" in fields[:-1] else ""
                    rules.entries.append(Rule(output, mode, mode == "disable", mirror))
        active.remove(path)
        return True

    if not load(f"{config}/hypr/hyprland.lua", optional=True):
        if not load(f"{config}/hypr/hyprland.conf", optional=True):
            rules.unavailable = True
    return rules


def _sources(host: Host, pattern: str) -> list[str]:
    if not any(char in pattern for char in "*?["):
        return [pattern]
    directory, basename = posixpath.split(pattern)
    try:
        return [f"{directory}/{name}" for name in host.list_dir(directory) if fnmatch.fnmatchcase(name, basename)]
    except OSError:
        return []


def _table(text: str, lua: bool) -> Rule | None:
    fields = {}
    statements = (re.findall(r'''(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^,;\n])+''', text)
                  if lua else re.split(r"\n|;", text))
    for statement in statements:
        if "=" not in statement:
            continue
        key, value = map(str.strip, statement.split("=", 1))
        fields[key] = value[1:-1] if re.fullmatch(r"(['\"]).*\1", value) else value
    output = fields.get("output", "")
    mode = fields.get("mode", fields.get("resolution", "preferred"))
    if lua:
        for key in ("output", "mode"):
            if key in fields and ("\\" in fields[key] or not re.search(rf"\b{key}\s*=\s*(['\"])[^'\"]*\1", text)):
                return None
    return Rule(output, mode, fields.get("disabled", "false") in ("true", "1", "yes"),
                fields.get("mirror", fields.get("mirror_of", "")))
