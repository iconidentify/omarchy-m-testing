"""Privacy: what may reach a report or a recording, and the evidence scrubber.

Two rules, applied to every report before it is written, shown or uploaded:

1. Allowlist. Only the fields in REPORT_ALLOWLIST reach the report; anything
   else a check or the machine description carries is dropped. The allowlist
   mirrors schema/report-v1.schema.json (a Seam A test keeps them equal).
2. Scrubbed, text-only, bounded evidence. Every evidence line passes the
   Scrubber, which replaces MAC addresses, IP addresses, Wi-Fi network names,
   home paths, hostnames, usernames, e-mail addresses, serial numbers, disk
   identifiers, UUIDs and long hex identifiers with placeholders such as <mac> or <ssid>.
   Evidence is text only (non-text lines are replaced by a note) and at most
   EVIDENCE_BUDGET_BYTES (64 KiB) per report.

Recordings (recording.py) pass the same Scrubber before they are saved.

The Scrubber works from patterns plus what this machine tells it about
itself (Scrubber.for_host): its hostname, the accounts under /home and the
names of saved network connections, so those are removed wherever they appear.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from .host import Host

EVIDENCE_BUDGET_BYTES = 64 * 1024
EVIDENCE_LINE_MAX_CHARS = 500
EVIDENCE_LINES_PER_CHECK = 50

NON_TEXT_NOTE = "[non-text evidence removed]"
TRUNCATED_NOTE = "[evidence truncated: 64 KiB report limit]"

HOSTNAME_PATH = "/proc/sys/kernel/hostname"
HOME_DIR = "/home"
SAVED_CONNECTIONS = ["nmcli", "--get-values", "NAME", "connection", "show"]

# Only these fields reach a report. A dict lists allowed keys (True: keep the
# value as is); a one-item list means "a list of these".
_CLASSIFICATION = {
    "outcome": True,
    "feature": True,
    "layer": True,
    "expected": {"asahi": True, "aurora": True, "omarchy": True},
}
_CHECK = {"id": True, "kind": True, "status": True, "evidence": True, "classification": _CLASSIFICATION}
REPORT_ALLOWLIST: dict[str, Any] = {
    "schema_version": True,
    "tool": {"name": True, "version": True},
    "consent_version": True,
    "catalogue_version": True,
    "machine": {"model": True, "board": True, "soc": True, "chip": True, "arch": True, "kernel": True},
    "checks": [_CHECK],
}
# Free-text report fields that are scrubbed like evidence. The model is the
# device-tree model string, constrained by the schema, and is left alone.
_SCRUBBED_MACHINE_FIELDS = ("kernel",)

# Names that are never personal and would wreck logs if scrubbed as hints
# (the image's default hostname is "omarchy", Arch's is "archlinux").
_NOT_PERSONAL = {
    "root", "nobody", "localhost", "omarchy", "archlinux", "alarm", "linux", "lo",
    "wlan0", "eth0", "wired connection 1",
}
_SYSTEM_USERS = {
    "root", "nobody", "dbus", "polkitd", "rtkit", "avahi", "colord", "gdm", "sddm", "greeter",
    "http", "git", "alpm", "dnsmasq", "uuidd", "systemd", "user", "daemon", "bin", "mail", "ftp",
}

_HEX = "[0-9A-Fa-f]"
_H16 = f"{_HEX}{{1,4}}"
_SYSLOG_TIME = r"[A-Z][a-z]{2} [ \d]\d \d\d:\d\d:\d\d(?:\.\d+)?"
_FULL_TIME = r"[A-Z][a-z]{2} \d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?:\.\d+)? [A-Z][A-Za-z0-9+-]{1,5}"
_ISO_TIME = r"\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(?:[.,]\d+)?(?:[+-]\d\d:?\d\d|Z)?"
_USER = r"[a-z_][a-z0-9_.-]*"
_UNIT_SUFFIX = re.compile(r"\.(service|socket|target|timer|mount|slice|scope|device|path|swap|automount)$")

# (pattern, replacement) in the order they are applied. Replacements only
# use characters none of the later patterns can match.
_RULES: list[tuple[re.Pattern, Any]] = []


def _rule(pattern: str, replacement: Any, flags: int = 0) -> None:
    _RULES.append((re.compile(pattern, flags), replacement))


def _keep_unless_system(group: int, placeholder: str, prefix_groups: tuple[int, ...] = (1,), suffix_groups: tuple[int, ...] = ()):
    def replace(m: re.Match) -> str:
        name = m.group(group)
        if name.lower() in _SYSTEM_USERS or name.startswith("systemd-") or name.startswith("<"):
            return m.group(0)
        return "".join(m.group(g) or "" for g in prefix_groups) + placeholder + "".join(m.group(g) or "" for g in suffix_groups)
    return replace


def _email(m: re.Match) -> str:
    if _UNIT_SUFFIX.search(m.group(2)):
        return m.group(0)  # systemd template units such as user@1000.service
    return "<email>"


# Home-directory paths: the account name and everything under it.
_rule(r"(?<![\w.~-])(?:/home|/Users|/var/home)/[^\s'\"`:;,()\[\]{}<>]+", "<home>")
_rule(r"(?<![\w.-])/root/[^\s'\"`:;,()\[\]{}<>]*", "<home>")
_rule(r"(?<![\w/])~/[^\s'\"`:;,()\[\]{}<>]*", "<home>")
# E-mail and user@host addresses.
_rule(r"(?<![\w.%+-])([A-Za-z0-9._%+-]+)@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)", _email)
# Device-tree properties that carry per-unit values (dtc output).
_rule(r"(?i)\b((?:local-)?(?:mac|bd)-address|[\w,-]*serial-?(?:number|no)[\w,-]*|[\w,-]*uuid|[\w,-]*nonce|[\w,-]*ecid|mlb-[\w-]+)(\s*=\s*)(\[[^\]]*\]|\"[^\"]*\"(?:\s*,\s*\"[^\"]*\")*|<[^>]*>)", r"\1\2<redacted>")
# Serial numbers in tool output (lsusb, SerialNumber:, serial=...).
_rule(r"(?i)\b(serial[ _-]?(?:number|no|num)|ID_SERIAL(?:_SHORT)?)(\s*[:=]\s*)(\"?)([^\s\",;]+)\3", r"\1\2<serial>")
_rule(r"\b(iSerial\s+\d+\s+)(\S.*)$", r"\1<serial>")
# Disk identifiers: /dev/disk/by-* names and FAT volume ids (UUID=ABCD-1234).
_rule(r"(/dev/disk/by-(?:uuid|partuuid|id|label|partlabel|diskseq|path)/)[^\s'\"`:;,()\[\]{}<>]+", r"\1<disk>")
_rule(r"(?i)\b((?:PART)?UUID=\"?)[0-9A-F]{4}-[0-9A-F]{4}\b", r"\1<disk>")
# SSH key fingerprints.
_rule(r"\b(SHA256|MD5):[A-Za-z0-9+/:=]{16,}", r"\1:<fingerprint>")
# UUIDs (disk, partition, connection and boot identifiers).
_rule(rf"(?<![0-9A-Fa-f]){_HEX}{{8}}-{_HEX}{{4}}-{_HEX}{{4}}-{_HEX}{{4}}-{_HEX}{{12}}(?![0-9A-Fa-f])", "<uuid>")
# MAC and Bluetooth addresses, and longer byte runs that embed them
# (firewall logs print MAC=<dst>:<src>:<ethertype>).
_rule(rf"(?<![0-9A-Fa-f:-]){_HEX}{{2}}([:-])(?:{_HEX}{{2}}\1){{4,}}{_HEX}{{2}}(?![0-9A-Fa-f]|[:-]{_HEX})", "<mac>")
# IPv6 (full or compressed; must contain a hex group, so C++ "::" survives).
_rule(
    rf"(?<![\w:.])(?:(?:{_H16}:){{7}}{_H16}|(?:{_H16}(?::{_H16}){{0,6}})?::(?:{_H16}(?::{_H16}){{0,6}})?(?<=[0-9A-Fa-f]))(?:%[\w.-]+)?(?![\w:])",
    "<ip>",
)
# IPv4, but not inside longer dotted versions such as 23.20.95.0.40.50.92.
_rule(r"(?<![\w.-])(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(?![\w]|\.\d)", "<ip>")
# Long hex identifiers (boot and machine ids, hashes, kernel pointers).
_rule(rf"(?<![0-9A-Za-z])(?:0x)?{_HEX}{{16,}}(?![0-9A-Za-z])", "<hex>")
# Wi-Fi network names in NetworkManager, iwd, wpa_supplicant, iw and nmcli output.
_rule(r"(?i)\b(e?ssid)(\s*[:=]?\s*)(['\"])(.*?)\3", r"\1\2\3<ssid>\3")
_rule(r"(?i)\b(e?ssid)(\s*[:=]\s*)(?!['\"<])([^,\n]*?[^,\s])(?=,|\s*$|\s+[\w-]+[:=])", r"\1\2<ssid>")
_rule(r"(?i)\b(connection|access point|network|connected to|to network|for network|known network)(\s+)'([^'\n]*)'", r"\1\2'<ssid>'")
_rule(r"^(\s*ssid )(\S.*)$", r"\1<ssid>")
_rule(r"(?i)\b((?:connected|connecting|joined|joining) to network\s+|Wireless network\s+)(?!['<])(\S+)", r"\1<ssid>")
_rule(r"(policy: set )'[^'\n]*'", r"\1'<ssid>'")
_rule(r"(audit: op=\"connection[\w-]*\".*?\bname=)\"[^\"]*\"", r'\1"<ssid>"')
_rule(r"(?m)^(\s*[\w.-]+:wifi:[\w ()-]+:)(?!<ssid>)(.+)$", r"\1<ssid>")
_rule(r"(?m)^(\s*Connected network\s+)(\S.*?)\s*$", r"\1<ssid>")
_rule(r"(/var/lib/iwd/)[^/\s]+?(\.(?:psk|open|8021x))\b", r"\1<ssid>\2")
_rule(r"(system-connections/)[^/\s'\"]+", r"\1<ssid>")
# Hostnames: journal and syslog line prefixes, uname -a, host=... and hostnamed.
_rule(rf"(?m)^(\s*(?:{_FULL_TIME}|{_SYSLOG_TIME}|{_ISO_TIME})\s+)(?!<)([A-Za-z0-9][A-Za-z0-9.-]*)(\s+[^\s\[\]:]+(?:\[\d+\])?:)", r"\1<hostname>\3")
_rule(r"(?m)^(\s*\[\s*\d+\.\d+\]\s+)(?!<)([A-Za-z0-9][A-Za-z0-9.-]*)(\s+(?:kernel|[^\s\[\]:]+\[\d+\]):)", r"\1<hostname>\3")
_rule(r"(?m)^(\s*Linux )(\S+)( \d+\.\d+)", r"\1<hostname>\3")
_rule(r"(?i)\b((?:static |transient |pretty )?host(?:_?name)?)(\s*(?:=>|[:=])\s*)(['\"]?)(?!<)([A-Za-z0-9][\w.-]*)\3", r"\1\2\3<hostname>\3")
_rule(r"(?i)\b(hostname (?:set )?to\s+)<?(?!hostname>)[\w.-]+>?", r"\1<hostname>")
# Usernames: sudo, PAM, logind, environment-style keys, uid=N(name).
_rule(rf"(?m)^(.*?\s)({_USER})(\s+:\s+(?=(?:TTY|PWD|USER|COMMAND)=))", _keep_unless_system(2, "<user>", (1,), (3,)))
_rule(rf"\b((?:USER|LOGNAME|SUDO_USER|user|ruser|acct)=\"?)({_USER})", _keep_unless_system(2, "<user>", (1,)))
_rule(rf"(?i)\b((?:for|of) user\s+'?)({_USER})", _keep_unless_system(2, "<user>", (1,)))
_rule(rf"\b(by\s+)({_USER})(\(uid=)", _keep_unless_system(2, "<user>", (1,), (3,)))
_rule(rf"\b(uid=\d+\()({_USER})(\))", _keep_unless_system(2, "<user>", (1,), (3,)))
_rule(rf"(?i)\b(new session \S+ of user\s+|Accepted \S+ for\s+|Invalid user\s+)({_USER})", _keep_unless_system(2, "<user>", (1,)))


class Scrubber:
    """Replaces personal identifiers in text with placeholders."""

    def __init__(self, hostnames: Iterable[str] = (), users: Iterable[str] = (), networks: Iterable[str] = ()):
        # Hostnames match in any case (DNS ignores case); account and network
        # names only exactly, so a user called "max" leaves "M2 Max" alone.
        hints = []
        for values, placeholder, flags in (
            (networks, "<ssid>", 0),
            (hostnames, "<hostname>", re.IGNORECASE),
            (users, "<user>", 0),
        ):
            for value in values:
                value = value.strip()
                if len(value) < 3 or value.lower() in _NOT_PERSONAL or value.startswith("<"):
                    continue
                hints.append((value, placeholder, flags))
        # Longest first, so "omarchy-m2-max" goes before a network named "omarchy-m2".
        hints.sort(key=lambda hint: -len(hint[0]))
        self._hints = [
            (re.compile(rf"(?<![\w-]){re.escape(value)}(?![\w-])", flags), placeholder)
            for value, placeholder, flags in hints
        ]

    @classmethod
    def for_host(cls, host: Host) -> "Scrubber":
        """Learn this machine's hostname, accounts and saved network names."""
        hostnames: list[str] = []
        try:
            hostnames = [host.read_file(HOSTNAME_PATH).decode("utf-8", "replace").strip()]
        except OSError:
            pass
        try:
            users = [name for name in host.list_dir(HOME_DIR) if not name.startswith(".")]
        except OSError:
            users = []
        saved = host.run(SAVED_CONNECTIONS)
        networks = saved.stdout.splitlines() if saved.returncode == 0 else []
        return cls(hostnames=hostnames, users=users, networks=networks)

    def scrub(self, text: str) -> str:
        """Scrub each line on its own, so no pattern can reach across lines."""
        return "".join(self._scrub_line(line) for line in text.splitlines(keepends=True))

    def _scrub_line(self, line: str) -> str:
        body = line.rstrip("\r\n")
        end = line[len(body):]
        for pattern, replacement in _RULES:
            body = pattern.sub(replacement, body)
        for pattern, placeholder in self._hints:
            body = pattern.sub(placeholder, body)
        return body + end


def _is_text(line: str) -> bool:
    return "\ufffd" not in line and not any(ord(c) < 32 and c != "\t" for c in line)


def _evidence_line(line: Any, scrubber: Scrubber) -> str:
    if not isinstance(line, str) or not _is_text(line):
        return NON_TEXT_NOTE
    line = scrubber.scrub(line)
    if len(line) > EVIDENCE_LINE_MAX_CHARS:
        line = line[: EVIDENCE_LINE_MAX_CHARS - 3] + "..."
    return line


def _allowed(value: Any, allowlist: Any) -> Any:
    if allowlist is True:
        return value
    if isinstance(allowlist, list):
        return [_allowed(item, allowlist[0]) for item in value] if isinstance(value, list) else []
    if isinstance(allowlist, dict) and isinstance(value, dict):
        return {key: _allowed(value[key], allowlist[key]) for key in allowlist if key in value}
    return {}


def enforce(report: dict, scrubber: Scrubber) -> dict:
    """The report with only allowlisted fields and scrubbed, bounded, text-only evidence."""
    report = _allowed(report, REPORT_ALLOWLIST)
    machine = report.get("machine", {})
    for name in _SCRUBBED_MACHINE_FIELDS:
        if isinstance(machine.get(name), str):
            machine[name] = scrubber.scrub(machine[name])

    # The truncation note is always reserved, so the total never exceeds the budget.
    budget = EVIDENCE_BUDGET_BYTES - len(TRUNCATED_NOTE.encode("utf-8"))
    exhausted = False
    for check in report.get("checks", []):
        if "evidence" not in check:
            continue
        lines = check["evidence"] if isinstance(check["evidence"], list) and not exhausted else []
        lines = [_evidence_line(line, scrubber) for line in lines]
        if len(lines) > EVIDENCE_LINES_PER_CHECK:
            dropped = len(lines) - (EVIDENCE_LINES_PER_CHECK - 1)
            lines = lines[: EVIDENCE_LINES_PER_CHECK - 1] + [f"[{dropped} more lines not included]"]
        kept = []
        for line in lines:
            size = len(line.encode("utf-8"))
            if size > budget:
                kept.append(TRUNCATED_NOTE)
                exhausted = True
                break
            kept.append(line)
            budget -= size
        check["evidence"] = kept
    return report


def evidence_bytes(report: dict) -> int:
    """Total UTF-8 size of a report's evidence lines."""
    return sum(len(line.encode("utf-8")) for check in report.get("checks", []) for line in check.get("evidence", []))
