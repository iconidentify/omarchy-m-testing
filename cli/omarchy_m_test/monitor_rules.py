"""Read monitor intent without executing user configuration (hyprlang and Omarchy's Lua).

Follow static sources in order. A named rule wins over the fallback; the
last rule for a selector wins. Anything this reader can't resolve statically
leaves intent unknown, so the native-mode check skips rather than fails:

  - a monitor rule whose output, mode, disabled or mirror is not one plain
    literal (a concatenation, a variable, a call), whose other fields call or
    define anything, or that sits inside a block (if, for, while, a function)
    or a branching (and/or) statement;
  - a load this reader can't resolve: require() of anything but a literal
    module, dofile/loadfile/load other than Omarchy's bootstrap line, any
    package.* change but a plain package.path prepend, goto, an early return;
  - a conditional load of a module that sets monitor rules, is unknown, or
    changes package.path. A conditional load of a module with no monitor
    rules doesn't matter either way, which is how Omarchy's own
    `if ... then require(...) end` bindings stay readable;
  - loading a module with monitor rules a second time (caching, reloads).

Lua modules resolve the way Omarchy's bootstrap sets package.path
(~/.local/state, ~/.config, $OMARCHY_PATH), each loaded once, and only after
the bootstrap line ran and only while bootstrap.lua is Omarchy's current one.
Omarchy's helpers are read for what they do, not executed, and only while
their bodies are Omarchy's current ones (KNOWN_HELPERS) and only through
reads of their own fields: require_optional.module("x") is an optional load
of x; require_all.files(dir, prefix, {exclude=..., reload=...}) loads dir's
regular *.lua files in sorted order, when dir is literals joined with
paths.home/config_home/state_home/omarchy_path or a local set that way once.

A command the configuration runs that names a monitor-changing tool
(hyprctl keyword monitor/eval, kanshi, wlr-randr...) is unknown too; a
command built at runtime can't be seen, like any live hyprctl override.

hyprlang is read line by line (Reader.conf): top-level monitor, source and
$variable lines and monitorv2 blocks; anything it can't read for certain is
unknown. With monitorv2 blocks, an output whose matching rules disagree is
unknown (how v2 ranks against monitor= lines isn't modelled).
"""

from __future__ import annotations

import fnmatch
import hashlib
import posixpath
import re
from dataclasses import dataclass, field

from .host import Host

MAX_READS = 256  # files read (a module search also tries absent paths, which cost nothing)
MAX_ATTEMPTS = 1024
MAX_NESTING = 32  # files loading files: deeper than this is unknown
KEY_FIELDS = ("output", "mode", "resolution", "disabled", "mirror", "mirror_of")
BOOTSTRAP = 'dofile((os.getenv("OMARCHY_PATH")or"/usr/share/omarchy").."/default/hypr/bootstrap.lua")'


@dataclass(frozen=True)
class Rule:
    output: str
    mode: str = "preferred"
    disabled: bool = False
    mirror: str = ""

    def matches(self, name: str, description: str) -> bool:
        return selects(self.output, name, description)


def selects(selector: str, name: str, description: str) -> bool:
    return description.startswith(selector[5:].strip()) if selector.startswith("desc:") else selector == name


@dataclass
class Rules:
    entries: list[Rule] = field(default_factory=list)
    unavailable: bool = False
    v2: bool = False  # monitorv2 blocks: how they rank against monitor= lines isn't modelled

    def ambiguous(self, name: str, description: str) -> bool:
        """With monitorv2 blocks, the rules that match an output must agree, or which one wins matters."""
        if not self.v2:
            return False
        matching = {(r.mode, r.disabled, r.mirror) for r in self.entries if not r.output or r.matches(name, description)}
        return len(matching) > 1

    def for_output(self, name: str, description: str) -> Rule:
        named = [rule for rule in self.entries if rule.output and rule.matches(name, description)]
        fallback = [rule for rule in self.entries if not rule.output]
        return (named or fallback or [Rule(name)])[-1]


def intent(host: Host, outputs: list[dict]) -> dict[str, dict]:
    """Only policy flags leave the host, never config text or description selectors."""
    rules = read(host)
    effective = {o["name"]: (rules.for_output(o["name"], o.get("description", "")), o.get("description", "")) for o in outputs}
    found = {}
    for name, (rule, description) in effective.items():
        mirrored = bool(rule.mirror) or any(
            other != name and selects(r.mirror, name, description) for other, (r, _) in effective.items() if r.mirror)
        found[name] = {"preferred": rule.mode == "preferred", "disabled": rule.disabled,
                       "mirrored": mirrored, "unavailable": rules.unavailable or rules.ambiguous(name, description)}
    return found


def _env(host: Host, name: str, fallback: str) -> str:
    return host.env(name) or fallback


class Reader:
    def __init__(self, host: Host):
        self.host = host
        home = host.env("HOME") or ""
        self.home = home
        self.config = _env(host, "XDG_CONFIG_HOME", f"{home}/.config")
        self.paths = {"home": home, "config_home": self.config,
                      "state_home": _env(host, "XDG_STATE_HOME", f"{home}/.local/state"),
                      "omarchy_path": _env(host, "OMARCHY_PATH", "/usr/share/omarchy")}
        # Omarchy's bootstrap: package.path is ~/.local/state, ~/.config, then $OMARCHY_PATH
        self.lua_roots = [f"{home}/.local/state", f"{home}/.config", host.env("OMARCHY_PATH") or "/usr/share/omarchy"]
        self.rules = Rules()
        self.variables = {"HOME": home, "XDG_CONFIG_HOME": self.config}  # hyprlang $variables: shared across sources
        self.active: set[str] = set()
        self.loaded: set[str] = set()
        self.ruled: set[str] = set()  # modules whose loading set monitor rules: loading them again isn't modelled
        self.bootstrapped = False
        self.reads = 0
        self.attempts = 0

    def text(self, path: str) -> str | None:
        """None when absent; raises _Unknown when present but unreadable or past the budget."""
        self.attempts += 1
        if self.attempts > MAX_ATTEMPTS or self.reads >= MAX_READS:
            raise _Unknown
        try:
            data = self.host.read_file(path)
        except FileNotFoundError:
            return None
        except OSError:  # a FIFO, a device, too large, too slow (the host refuses them): counts as a read
            self.reads += 1
            raise _Unknown
        self.reads += 1
        try:
            return data.decode("utf-8")
        except UnicodeError:
            raise _Unknown

    # -- Lua ---------------------------------------------------------------

    def find_module(self, module: str) -> tuple[str, str] | None:
        relative = module.replace(".", "/") + ".lua"
        for root in self.lua_roots:
            path = f"{root}/{relative}"  # as Lua's searcher builds it: no normalising (a/../b and a/ follow links)
            text = self.text(path)
            if text is not None:
                return path, text
        return None

    def require(self, module: str, sink: Rules, optional: bool = False, reload: bool = False) -> None:
        if not self.bootstrapped:
            raise _Unknown  # package.path is Omarchy's only once its bootstrap ran
        if module in self.ruled:
            raise _Unknown  # cached or loaded again (reload, a module returning false): not modelled
        if module in self.loaded and not reload:
            return
        found = self.find_module(module)
        if found is None:
            if not optional:
                raise _Unknown
            return
        path, text = found
        self.loaded.add(module)
        if module in HELPERS:
            if helper_digest(_tokens(text)) != KNOWN_HELPERS[HELPERS[module]]:
                raise _Unknown  # not the helper this reader knows how to read
            return  # read for what it does where it's called (below), not as configuration
        before, roots = len(sink.entries), list(self.lua_roots)
        self.lua(path, text, sink)
        if len(sink.entries) != before or self.lua_roots != roots:
            self.ruled.add(module)  # it has effects: loading it again isn't modelled

    def bootstrap(self) -> None:
        if self.bootstrapped:
            raise _Unknown  # a second bootstrap clears the module cache: not modelled
        path = f"{self.host.env('OMARCHY_PATH') or '/usr/share/omarchy'}/default/hypr/bootstrap.lua"
        text = self.text(path)
        if text is None or helper_digest(_tokens(text)) != KNOWN_HELPERS["bootstrap"]:
            raise _Unknown  # not the bootstrap this reader knows the package.path of
        self.bootstrapped = True

    def probe(self, load) -> None:
        """A conditional load: harmless unless what it loads sets monitor rules (or can't be read)."""
        trial = Rules()
        loaded, roots = set(self.loaded), list(self.lua_roots)
        load(trial)
        if trial.entries or trial.unavailable or self.lua_roots != roots:
            raise _Unknown  # it sets rules, or changes where later modules are found, only if it runs
        self.loaded = loaded  # it may not run: a later unconditional load still reads the module

    def lua(self, path: str, text: str, sink: Rules) -> None:
        if path in self.active or len(self.active) >= MAX_NESTING:
            raise _Unknown
        self.active.add(path)
        try:
            _LuaFile(self, path, _tokens(text), sink).run()
        finally:
            self.active.discard(path)

    # -- hyprlang -----------------------------------------------------------

    def conf(self, path: str, text: str) -> None:
        """hyprlang, line by line. Only top-level monitor, source and $variable lines and top-level monitorv2
        blocks are read; other keys and categories are skipped. Anything this can't read for certain (a
        hyprlang directive other than noerror, an escaped #, a line continuation, {{math}}, a monitor or source key inside a
        category, a $ left after expansion) leaves intent unknown."""
        if path in self.active or len(self.active) >= MAX_NESTING:
            raise _Unknown
        self.active.add(path)
        depth, block = 0, None  # category nesting; the open top-level monitorv2 block's fields
        for raw in text.split("\n"):
            stripped = raw.strip()
            directive = re.match(r"#\s*hyprlang\s+(\w+)", stripped)
            if directive and directive[1] != "noerror":
                raise _Unknown
            if stripped.startswith("#") and not stripped.startswith("##"):
                continue  # a comment line
            if "##" in raw or raw.rstrip().endswith("\\") or "{{" in raw:
                raise _Unknown
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            if line == "}":
                depth -= 1
                if depth < 0:
                    raise _Unknown
                if depth == 0 and block is not None:
                    self.rules.entries.append(_conf_table(block, self.expand))
                    self.rules.v2 = True
                    block = None
                continue
            category = re.fullmatch(r"([\w:.\-]+(?:\[[^\]]*\])?)\s*\{", line)
            if category:
                if category[1] == "monitorv2" and depth == 0:
                    block = {}
                elif category[1].startswith("monitorv2"):
                    raise _Unknown
                depth += 1
                continue
            assignment = re.fullmatch(r"([^=]+?)\s*=\s*(.*)", line)
            if not assignment:
                raise _Unknown  # not a line this reader knows
            key, value = assignment[1].strip(), assignment[2].strip()
            if "$" in key and not (depth == 0 and re.fullmatch(r"\$\w+", key)):
                raise _Unknown  # a key spelt through a variable, or a variable set inside a category
            if block is not None and depth == 1:
                if key in ("monitor", "source", "monitorv2") or "$" in key:
                    raise _Unknown  # a statement with effects inside the block
                block[key] = value
            elif depth > 0:
                if key in ("monitor", "source", "monitorv2") or key.startswith("$"):
                    raise _Unknown
            elif key.startswith("$"):
                if not re.fullmatch(r"\$\w+", key):
                    raise _Unknown
                self.variables[key[1:]] = self.expand(value)
            elif "$" in key:
                raise _Unknown  # a key spelt through a variable
            elif key.startswith("exec") and MONITOR_COMMAND.search(self.expand(value)):
                raise _Unknown  # exec-once = hyprctl keyword monitor ...: set at runtime, not in the files
            elif key == "source":
                self.source(path, self.expand(value))
            elif key == "monitor":
                value = self.expand(value)
                fields = [f.strip() for f in value.split(",")]
                if len(fields) < 2 or "$" in value:
                    raise _Unknown
                output, mode = fields[:2]
                if mode in ("transform", "addreserved"):
                    continue
                mirror = fields[fields.index("mirror") + 1] if "mirror" in fields[:-1] else ""
                self.rules.entries.append(Rule(output, mode, mode == "disable", mirror))
        if depth != 0:
            raise _Unknown
        self.active.discard(path)

    def expand(self, value: str) -> str:
        value = re.sub(r"\$(?:\{(\w+)\}|(\w+))", lambda m: self.variables.get(m[1] or m[2], m[0]), value)
        return self.home + value[1:] if value.startswith("~/") else value

    def absolute(self, raw: str, current: str) -> str:
        """Hyprland's absolutePath(): ~ is $HOME; a relative path joins the current file's directory, with only a
        leading ../ or ./ resolved in the text (the rest, and every absolute path, is left to the filesystem)."""
        if raw.startswith("~"):
            return self.home + raw[1:]
        if raw.startswith("/"):
            return raw
        directory = current[:current.rfind("/")]
        if raw.startswith("../"):
            return directory[:directory.rfind("/")] + raw[2:]
        if raw.startswith("./"):
            return directory + raw[1:]
        return f"{directory}/{raw}"

    def source(self, path: str, value: str) -> None:
        if "$" in value or len(value) < 2:
            raise _Unknown
        for source in self.sources(self.absolute(value, path)):
            source = self.absolute(source, path)
            found = self.text(source)
            if found is None:
                raise _Unknown
            self.conf(source, found)

    def sources(self, pattern: str) -> list[str]:
        """A glob that matches nothing (its directory absent or empty) sources nothing, as Hyprland's glob does."""
        if not any(char in pattern for char in "*?["):
            return [pattern]
        directory, basename = posixpath.split(pattern)
        if any(char in directory for char in "*?["):
            raise _Unknown  # a glob in a directory part: not read
        try:
            names = self.host.list_dir(directory)
        except FileNotFoundError:
            return []
        except OSError:
            raise _Unknown
        # glob(3): a wildcard doesn't match a leading dot
        return [f"{directory}/{name}" for name in names
                if fnmatch.fnmatchcase(name, basename) and (not name.startswith(".") or basename.startswith("."))]


class _Unknown(Exception):
    """Intent can't be read statically."""


def read(host: Host) -> Rules:
    reader = Reader(host)
    try:
        lua = f"{reader.config}/hypr/hyprland.lua"
        text = reader.text(lua)
        if text is not None:
            reader.lua(lua, text, reader.rules)
        else:
            conf = f"{reader.config}/hypr/hyprland.conf"
            text = reader.text(conf)
            if text is None:
                raise _Unknown
            reader.conf(conf, text)
    except (_Unknown, IndexError, RecursionError):  # a truncated statement or a depth this reader didn't expect
        reader.rules.unavailable = True
    return reader.rules


def _conf_table(block: dict[str, str], expand) -> Rule:
    fields = {}
    for key, value in block.items():
        value = expand(value)
        if key in KEY_FIELDS and "$" in value:
            raise _Unknown  # a variable this reader can't resolve
        fields[key] = value
    return Rule(fields.get("output", ""), fields.get("mode", fields.get("resolution", "preferred")),
                fields.get("disabled", "false") in ("true", "1", "yes"), fields.get("mirror", fields.get("mirror_of", "")))


# -- Lua, read as tokens -------------------------------------------------------

_TOKEN = re.compile(r"""
    (?P<space>\s+)
  | --\[(?P<ceq>=*)\[.*?\](?P=ceq)\]
  | (?P<comment>--[^\n]*)
  | \[(?P<leq>=*)\[(?P<long>.*?)\](?P=leq)\]
  | (?P<str>"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<num>0[xX][0-9a-fA-F.]+(?:[pP][-+]?\d+)?|\d+\.?\d*(?:[eE][-+]?\d+)?|\.\d+(?:[eE][-+]?\d+)?)
  | (?P<op>\.\.\.|\.\.|==|~=|<=|>=|::|//|<<|>>|.)
""", re.S | re.X)
OPEN = {"function", "if", "do", "repeat"}
CLOSE = {"end", "until"}


@dataclass(frozen=True)
class Tok:
    kind: str  # name, str, long, num, op
    value: str
    line: int
    depth: int  # block depth (if/for/while/do/function/repeat) at the token
    functions: int = 0  # how many function bodies it is inside

    def literal(self) -> str | None:
        """A plain string literal's text: no escapes, so what's written is what Lua sees."""
        return self.value[1:-1] if self.kind == "str" and "\\" not in self.value else None


def _tokens(text: str) -> list[Tok]:
    tokens, stack, line = [], [], 1
    for match in _TOKEN.finditer(text):
        kind, value = match.lastgroup, match[0]
        if kind in ("name", "str", "num", "op", "long"):
            if kind == "name" and value in CLOSE and stack:
                stack.pop()
            tokens.append(Tok(kind, value, line, len(stack), stack.count("function")))
            if kind == "name" and value in OPEN:
                stack.append(value)
        line += value.count("\n")
    return tokens


def _balanced(tokens: list[Tok]) -> bool:
    blocks, brackets = 0, 0
    for tok in tokens:
        if tok.kind == "name":
            blocks += (tok.value in OPEN) - (tok.value in CLOSE)
        elif tok.kind == "op" and tok.value in ("(", "[", "{", ")", "]", "}"):
            brackets += 1 if tok.value in "([{" else -1
        if blocks < 0 or brackets < 0:
            return False
    return blocks == 0 and brackets == 0


def _dotted(tokens: list[Tok], i: int) -> tuple[str, int]:
    """A dotted name starting at i (hl.monitor, require_all.files) and the index after it."""
    parts, j = [tokens[i].value], i + 1
    while j + 1 < len(tokens) and tokens[j].value == "." and tokens[j + 1].kind == "name":
        parts.append(tokens[j + 1].value)
        j += 2
    return ".".join(parts), j


def _group(tokens: list[Tok], i: int) -> int:
    """The index of the bracket closing the one at i, or raises _Unknown."""
    pairs, stack = {"(": ")", "{": "}", "[": "]"}, []
    for j in range(i, len(tokens)):
        value = tokens[j].value if tokens[j].kind == "op" else ""
        if value in pairs:
            stack.append(pairs[value])
        elif stack and value == stack[-1]:
            stack.pop()
            if not stack:
                return j
    raise _Unknown


def _split(tokens: list[Tok]) -> list[list[Tok]]:
    """Top-level comma- or semicolon-separated items."""
    items, item, depth = [], [], 0
    for tok in tokens:
        if tok.kind == "op" and tok.value in "({[":
            depth += 1
        elif tok.kind == "op" and tok.value in ")}]":
            depth -= 1
        if depth == 0 and tok.kind == "op" and tok.value in ",;":
            items.append(item)
            item = []
        else:
            item.append(tok)
    if item:
        items.append(item)
    return items


def _call_args(tokens: list[Tok], j: int) -> tuple[list[Tok], int]:
    """The argument tokens of a call at j: f(...), f"str" or f{...}; and the index after."""
    if j < len(tokens) and tokens[j].value in ("(", "{") and tokens[j].kind == "op":
        end = _group(tokens, j)
        return (tokens[j + 1:end] if tokens[j].value == "(" else tokens[j:end + 1]), end + 1
    if j < len(tokens) and tokens[j].kind == "str":
        return [tokens[j]], j + 1
    raise _Unknown


# Tokens after which an expression goes on (so a line break there doesn't end the statement).
CONTINUES = {"and", "or", "not", "..", "+", "-", "*", "/", "//", "%", "^", "#", "==", "~=", "<", "<=", ">", ">=",
             "&", "|", "~", "<<", ">>", "=", ",", "(", "[", "{"}
# Tokens that only start (or sit between) statements: what came before can't branch what follows.
STATEMENT = {"local", "if", "then", "else", "elseif", "end", "do", "while", "for", "repeat", "until", "return",
             "function", "goto", "break", ";"}
EFFECTS = {"hl", "require", "dofile", "loadfile", "load", "loadstring", "package", "_G", "_ENV",
           "require_all", "require_optional"}
# The real API and what Omarchy's bootstrap relies on: rebinding or replacing any of them isn't modelled.
SHADOWED = {"hl", "require", "dofile", "loadfile", "load", "loadstring", "package", "_G", "_ENV", "os", "io", "debug",
            "setmetatable", "getmetatable", "rawset", "string", "table", "pairs", "ipairs"}
LIBRARIES = {"os", "string", "table", "io"}  # used only as os.getenv(...), io.open(...) and the like
# A command the configuration runs that changes monitors itself (hyprctl keyword monitor, a layout tool):
# what it sets isn't in the files. Commands built at runtime can't be seen (like a live hyprctl override).
MONITOR_COMMAND = re.compile(r"\bhyprctl\b.*\b(?:keyword\s+monitor|eval|--batch|reload)\b|"
                             r"\b(?:kanshi|wlr-randr|shikane|nwg-displays|way-displays|wdisplays)\b", re.I)
OPAQUE = {"debug", "rawset", "rawget", "setmetatable", "getmetatable", "rawequal", "collectgarbage"}
HELPERS = {"default.hypr.paths": "paths", "default.hypr.require_all": "require_all",
           "default.hypr.require_optional": "require_optional"}
# The helper implementations this reader interprets, by digest of their tokens (comments and spacing don't count):
# Omarchy's current paths.lua, require_all.lua (with exclude and reload) and require_optional.lua. Any other body
# (an older or edited helper) leaves intent unknown rather than being guessed at.
KNOWN_HELPERS = {
    "paths": "06c24b72f4dda24d8cd3080b85e1b643998159254145b3cc996d3a2e1bed1bd2",
    "require_all": "b69b7d44910941e9bafaa6252082f8b39b40b8fa3ead3c3ca680e3198ccc0390",
    "require_optional": "03547db105b3d66d7e9d80f5aebc5f6c0f249ac4a5a9175e0559687fbe78456f",
    "bootstrap": "199761d1f1c8548296a6e4f805847981eb7158829146abbf72ab4a8a5677bad5",
}
HELPER_FIELDS = {"paths": {"home", "config_home", "state_home", "omarchy_path"},
                 "require_all": {"files"}, "require_optional": {"module"}}


def helper_digest(tokens: list["Tok"]) -> str:
    return hashlib.sha256("\0".join(t.value for t in tokens).encode("utf-8")).hexdigest()


def _bindings(tokens: list[Tok]) -> dict[str, int]:
    """How many times each name is bound (local, assignment, for variable, function name or parameter).
    A local is trusted as a known directory or helper only when it is bound once."""
    counts: dict[str, int] = {}

    def bind(tok: Tok) -> None:
        counts[tok.value] = counts.get(tok.value, 0) + 1

    brackets = 0
    for k, tok in enumerate(tokens):
        nxt = tokens[k + 1] if k + 1 < len(tokens) else None
        prev = tokens[k - 1] if k else None
        if tok.kind == "op" and tok.value in "([{":
            brackets += 1
        elif tok.kind == "op" and tok.value in ")]}":
            brackets = max(brackets - 1, 0)
        if tok.kind != "name":
            continue
        if tok.value in ("local", "for"):
            m = k + 1
            if m < len(tokens) and tokens[m].value == "function":
                m += 1
            while m < len(tokens) and tokens[m].kind == "name":
                bind(tokens[m])
                if m + 1 < len(tokens) and tokens[m + 1].value == ",":
                    m += 2
                else:
                    break
        elif tok.value == "function":
            m = k + 1
            while m < len(tokens) and tokens[m].value != "(":
                m += 1
            if m < len(tokens) and k + 1 < m and tokens[k + 1].kind == "name" and (prev is None or prev.value != "local"):
                bind(tokens[k + 1])  # function name() ... end: assigns name
            m += 1
            while m < len(tokens) and tokens[m].value != ")":
                if tokens[m].kind == "name":
                    bind(tokens[m])
                m += 1
        elif (prev is None or prev.value not in (".", ":", "local", "for", ",")) and nxt is not None and (
                nxt.value == "=" or (nxt.value == "," and brackets == 0)):
            bind(tok)  # name = ..., or the first of name, other = ...
        elif prev is not None and prev.value == "," and brackets == 0 and nxt is not None and nxt.value in ("=", ","):
            bind(tok)
    return counts


def _nesting(tokens: list[Tok]) -> list[int]:
    """Per token: how many brackets ((, [, {) it is inside."""
    depths, depth = [], 0
    for tok in tokens:
        if tok.kind == "op" and tok.value in (")", "]", "}"):
            depth = max(depth - 1, 0)
        depths.append(depth)
        if tok.kind == "op" and tok.value in ("(", "[", "{"):
            depth += 1
    return depths


def _branching(tokens: list[Tok]) -> list[bool]:
    """Per token: is it in a statement that already branched (an and/or before it, across line breaks too)?"""
    flags, branched, brackets = [], False, 0
    for k, tok in enumerate(tokens):
        value = tok.value if tok.kind in ("op", "name") else ""
        previous = tokens[k - 1] if k else None
        if previous is not None and brackets == 0 and (
                value in STATEMENT or previous.value == ";"
                or (tok.line != previous.line and previous.value not in CONTINUES and value not in CONTINUES - {"(", "{", "["})):
            branched = False
        if value in ("and", "or"):
            branched = True
        flags.append(branched)
        if tok.kind == "op" and value in ("(", "[", "{"):
            brackets += 1
        elif tok.kind == "op" and value in (")", "]", "}"):
            brackets = max(brackets - 1, 0)
    return flags


class _LuaFile:
    def __init__(self, reader: Reader, path: str, tokens: list[Tok], sink: Rules):
        self.reader, self.path, self.tokens, self.sink = reader, path, tokens, sink
        self.locals: dict[str, str] = {}  # local name -> a statically known directory
        self.helpers: dict[str, str] = {}  # local name -> which Omarchy helper it is bound to (paths, require_all...)
        self.branched = _branching(tokens)
        self.bound = _bindings(tokens)
        self.nesting = _nesting(tokens)
        self.helper_requires: set[int] = set()  # the require tokens that bound a helper (local name = require "...")
        self.helper_names: set[str] = set()  # names ever bound to a helper here
        self.helper_bindings: set[int] = set()  # the name tokens of those bindings
        if any(t.kind == "op" and t.value == "::" for t in tokens):
            raise _Unknown  # labels (goto): not read
        if any(t.kind in ("str", "long") and MONITOR_COMMAND.search(t.value) for t in tokens):
            raise _Unknown  # it runs (or may run) a command that sets monitors
        if any(name in self.bound for name in SHADOWED):
            raise _Unknown  # hl, require, package... rebound here: what they do isn't the real API

    def conditional(self, i: int) -> bool:
        """Inside a block, or in a statement that branches (and/or): it may not run."""
        return self.tokens[i].depth > 0 or self.branched[i]

    def load(self, i: int, action) -> None:
        if self.conditional(i):
            self.reader.probe(action)
        else:
            action(self.sink)

    def returns(self, i: int) -> None:
        """The chunk returns here. At the top level that's its last statement (Lua allows nothing after it);
        inside a block (if ... then return end) it may return early: nothing after the block may set rules or load."""
        depth = self.tokens[i].depth
        if depth == 0:
            return
        after = next((k for k in range(i + 1, len(self.tokens)) if self.tokens[k].depth < depth), len(self.tokens))
        for tok in self.tokens[after:]:
            if tok.kind == "name" and (tok.value in EFFECTS or tok.value in self.helper_names):
                raise _Unknown

    def goes_on(self, end: int) -> bool:
        """Does the expression ending before end continue on the next line (and ..., .field, (...), "...")?"""
        if end >= len(self.tokens) or self.tokens[end].value == ";":
            return False
        nxt = self.tokens[end]
        return nxt.kind in ("str", "long") or nxt.value in CONTINUES or nxt.value in (".", ":")

    def helper(self, name: str) -> str | None:
        """ra.files -> "require_all.files" when ra is bound (once) here to Omarchy's require_all; else None."""
        head, _, rest = name.partition(".")
        if head in self.helpers and rest and self.bound.get(head) == 1:
            return f"{self.helpers[head]}.{rest}"
        return None

    def run(self) -> None:
        tokens, i = self.tokens, 0
        if tokens and (tokens[-1].value in CONTINUES or not _balanced(tokens)):
            raise _Unknown  # a truncated file: Hyprland wouldn't load it as written
        while i < len(tokens):
            tok = tokens[i]
            if tok.kind != "name" or (i and tokens[i - 1].value in (".", ":") and tokens[i - 1].kind == "op"):
                i += 1
                continue
            name, j = _dotted(tokens, i)
            if name.split(".")[0] in ("_G", "_ENV"):
                if "." not in name:
                    raise _Unknown  # the globals table itself: anything could be reached through it
                name = name.split(".", 1)[1]
            head = name.split(".")[0]
            called = self.helper(name)
            if called is None and (name in ("require_all.files", "require_optional.module")
                                   or name.split(".")[0] in self.helper_names and i not in self.helper_bindings):
                raise _Unknown  # a helper call this reader can't attribute
            if name == "goto":
                raise _Unknown
            if head in OPAQUE or (head in LIBRARIES and not (
                    name.count(".") == 1 and j < len(tokens) and (tokens[j].value == "(" or tokens[j].kind == "str"))):
                raise _Unknown  # os/string/table only as calls of their functions: an alias, index or write escapes
            if "." in name and name.split(".")[0] in SHADOWED and name != "package.path" and j < len(tokens) \
                    and tokens[j].kind == "op" and tokens[j].value in ("=", ","):
                raise _Unknown  # hl.monitor = ..., require_all.files = ...: the API itself replaced
            if name == "return" and tok.functions == 0:
                self.returns(i)
            if head in self.helpers:
                # only reads of a helper's own fields: a write, an index or an alias could change what it does
                field = name.split(".")[1] if name.count(".") == 1 else None
                after = tokens[j] if j < len(tokens) else None
                if (field not in HELPER_FIELDS[self.helpers[head]]
                        or (after is not None and after.kind == "op" and (after.value in ("=", "[", ":", ".")
                                                                          or (after.value == "," and self.nesting[i] == 0)))):
                    raise _Unknown  # paths.x = ..., paths.x, y = ...: what it holds may change
            if name == "hl.monitor" or name.startswith("hl.monitor."):
                i = self.monitor(i, j)
            elif name == "hl" and (j >= len(tokens) or tokens[j].value != "."):
                raise _Unknown  # hl["monitor"], hl:monitor, hl passed on or aliased: not read
            elif name == "require":
                i = self.require(i, j)
            elif called == "require_optional.module":
                args, i = _call_args(tokens, j)
                module = args[0].literal() if len(args) == 1 else None
                if module is None:
                    raise _Unknown
                self.reader.probe(lambda sink, m=module: self.reader.require(m, sink, optional=True))
            elif called == "require_all.files":
                i = self.require_all(i, j)
            elif name in ("dofile", "loadfile", "load", "loadstring"):
                args, after = _call_args(tokens, j)
                if name != "dofile" or "".join(t.value for t in args) != BOOTSTRAP[7:-1] or self.conditional(i):
                    raise _Unknown
                self.reader.bootstrap()
                i = after
            elif name == "package" or name.startswith("package."):
                i = self.package_path(i, j)
            elif name == "local" and j + 2 < len(tokens) and tokens[j].kind == "name" and tokens[j + 1].value == "=":
                self.local(tokens[j].value, j + 2, tok.depth)
                i = j + 1  # read the value's own calls
            else:
                i = j
        return None

    def local(self, name: str, start: int, depth: int) -> None:
        """local name = <value> on one line: a known directory, or an Omarchy helper's require; else neither."""
        tokens = self.tokens
        self.locals.pop(name, None)
        self.helpers.pop(name, None)
        end = start
        while end < len(tokens) and tokens[end].line == tokens[start].line and tokens[end].value != ";":
            end += 1
        value = tokens[start:end]
        if not value or depth or self.branched[start] or value[-1].value in CONTINUES or self.goes_on(end):
            return  # it may not run, or the value goes on past the line: neither is known
        values = [t.value for t in value]
        module = (value[2].literal() if len(value) == 4 and values[:2] == ["require", "("] and values[3] == ")"
                  else value[1].literal() if len(value) == 2 and values[0] == "require" else None)
        if module in HELPERS:
            self.helpers[name] = HELPERS[module]
            self.helper_requires.add(start)
            self.helper_names.add(name)
            self.helper_bindings.add(start - 2)
            return
        directory = self.directory(value)
        if directory is not None:
            self.locals[name] = directory

    def monitor(self, i: int, j: int) -> int:
        tokens = self.tokens
        if self.conditional(i) or j != i + 3:
            raise _Unknown  # a rule that may not run, or hl.monitor.something
        args, after = _call_args(tokens, j)
        if not args or args[0].value != "{" or _group(args, 0) != len(args) - 1:
            raise _Unknown  # hl.monitor(screens[1]), hl.monitor({...}, more)
        rule = _lua_table(args)
        if rule is None:
            raise _Unknown
        self.sink.entries.append(rule)
        return after

    def require(self, i: int, j: int) -> int:
        tokens = self.tokens
        if j < len(tokens) and (tokens[j].kind == "str" or tokens[j].value == "("):
            args, after = _call_args(tokens, j)
            module = args[0].literal() if len(args) == 1 else None
            grouped = i > 0 and tokens[i - 1].value == "(" and tokens[i - 1].kind == "op"  # (require "x").field = ...
            if module in HELPERS and i not in self.helper_requires:
                raise _Unknown  # a helper only as `local name = require("...")`: other forms aren't followed
            if module is not None and not grouped and not (after < len(tokens) and tokens[after].kind == "op"
                                                           and tokens[after].value in (".", "[", ":")):
                self.load(i, lambda sink: self.reader.require(module, sink))
                return after
        raise _Unknown  # require(name), pcall(require, ...): what loads can't be read

    def require_all(self, i: int, j: int) -> int:
        args, after = _call_args(self.tokens, j)
        items = _split(args)
        if not 1 <= len(items) <= 3:
            raise _Unknown
        directory = self.directory(items[0])
        prefix = None
        if len(items) > 1:
            if len(items[1]) == 1 and items[1][0].value == "nil" and items[1][0].kind == "name":
                pass
            elif len(items[1]) == 1 and items[1][0].literal() is not None:
                prefix = items[1][0].literal()
            else:
                raise _Unknown
        exclude, reload = _options(items[2]) if len(items) > 2 else (set(), False)
        if directory is None:
            raise _Unknown

        def action(sink: Rules) -> None:
            try:
                names = self.reader.host.regular_files(directory)  # find -maxdepth 1 -type f
            except FileNotFoundError:
                return  # find prints nothing for a missing directory
            except OSError:
                raise _Unknown
            for filename in sorted(names):
                if not filename.endswith(".lua") or filename[:-4] in exclude:
                    continue
                # the helper require()s each name through package.path, as this does
                self.reader.require(f"{prefix}.{filename[:-4]}" if prefix is not None else filename[:-4], sink, reload=reload)

        self.load(i, action)
        return after

    def package_path(self, i: int, j: int) -> int:
        tokens = self.tokens
        if not (tokens[i].value == "package" and j < len(tokens) and tokens[j].value == "="
                and _dotted(tokens, i)[0] == "package.path"):
            raise _Unknown
        end = j + 1
        while end < len(tokens) and tokens[end].line == tokens[j + 1].line:
            end += 1
        expr = tokens[j + 1:end]
        # package.path = <directory> .. "/?.lua;" .. package.path
        if (len(expr) >= 7 and [t.value for t in expr[-4:]] == ["..", "package", ".", "path"]
                and expr[-5].literal() == "/?.lua;" and expr[-6].value == ".." and not self.conditional(i)
                and not self.goes_on(end)):
            directory = self.directory(expr[:-6])
            if directory is not None:
                self.reader.lua_roots.insert(0, directory)
                return end
        raise _Unknown

    def directory(self, expr: list[Tok]) -> str | None:
        """Literals joined (..) with paths.<field> or a known local; None if anything else."""
        if not expr:
            return None
        parts, i = [], 0
        while i < len(expr):
            tok = expr[i]
            if tok.literal() is not None:
                parts.append(tok.literal())
                i += 1
            elif tok.kind == "name":
                name, i = _dotted(expr, i)
                resolved = self.helper(name) or ""
                if resolved.startswith("paths.") and resolved[6:] in self.reader.paths:
                    parts.append(self.reader.paths[resolved[6:]])
                elif name in self.locals and self.bound.get(name) == 1:
                    parts.append(self.locals[name])
                else:
                    return None
            else:
                return None
            if i < len(expr):
                if expr[i].value != "..":
                    return None
                i += 1
                if i == len(expr):
                    return None
        return "".join(parts)  # as written: find and package.path see it unnormalised


def _options(item: list[Tok]) -> tuple[set[str], bool]:
    """require_all.files' options table: { reload = true, exclude = { ["name"] = true, name = true } }."""
    if not item or item[0].value != "{" or item[-1].value != "}":
        raise _Unknown
    exclude, reload = set(), False
    keys = [entry[0].value for entry in _split(item[1:-1]) if entry]
    if len(keys) != len(set(keys)):
        raise _Unknown  # a repeated option: the last wins in Lua, not modelled
    for entry in _split(item[1:-1]):
        if len(entry) == 3 and entry[0].kind == "name" and entry[1].value == "=" and entry[0].value == "reload":
            if entry[2].value not in ("true", "false"):
                raise _Unknown
            reload = entry[2].value == "true"
        elif len(entry) >= 4 and entry[0].value == "exclude" and entry[1].value == "=" and entry[2].value == "{":
            names = _split(entry[3:-1])
            if len({tuple(t.value for t in n) for n in names}) != len(names):
                raise _Unknown
            for name in names:
                values = [t.value for t in name]
                if len(name) == 5 and values[0] == "[" and name[1].literal() is not None and values[2:] == ["]", "=", "true"]:
                    exclude.add(name[1].literal())
                elif len(name) == 3 and name[0].kind == "name" and values[1:] == ["=", "true"]:
                    exclude.add(name[0].value)
                else:
                    raise _Unknown
        else:
            raise _Unknown
    return exclude, reload


def _inert(value: list[Tok]) -> bool:
    """Literals, names and operators only: nothing called, defined or built."""
    for k, tok in enumerate(value):
        if tok.kind == "op" and tok.value in ("(", "{", ":"):
            return False
        if tok.kind == "name" and tok.value == "function":
            return False
        if tok.kind in ("str", "long") and k and (
                (value[k - 1].kind == "name" and value[k - 1].value not in ("and", "or", "not"))
                or value[k - 1].value in ("]", ")")):
            return False  # f"x", t[1]"x": a call
    return True


def _lua_table(table: list[Tok]) -> Rule | None:
    """A monitor table whose output, mode, disabled and mirror are plain literals; None otherwise."""
    fields: dict[str, str] = {}
    for entry in _split(table[1:-1]):
        if len(entry) < 3 or entry[0].kind != "name" or entry[1].value != "=":
            return None  # positional values and ["key"] = ...: not read
        key, value = entry[0].value, entry[2:]
        if not _inert(value):
            return None  # a field that calls or defines something runs before the rule is made
        if key not in KEY_FIELDS:
            continue  # scale = omarchy_monitor_scale: doesn't decide the mode
        if len(value) != 1:
            return None  # "USB" .. "-1", a call, an expression
        literal = value[0].literal()
        if key == "disabled" and value[0].kind == "name" and value[0].value in ("true", "false"):
            literal = value[0].value
        if literal is None:
            return None
        fields[key] = literal
    return Rule(fields.get("output", ""), fields.get("mode", fields.get("resolution", "preferred")),
                fields.get("disabled", "false") == "true", fields.get("mirror", fields.get("mirror_of", "")))
