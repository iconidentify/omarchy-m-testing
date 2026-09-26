"""What this Mac runs: the Omarchy stack or reference distro, its packages,
disk encryption and candidate set. It becomes the report's "system" block.

Stacks, decided in this order:
  converged           the omarchy-mac package, or Omarchy's own omarchy package
                      (converged images, quattro-upstream installs); omacom's
                      omarchy-dev comes with omarchy-mac, so it stays converged
  mx-mac              the omarchy-mx-mac fork's omarchy-dev without omarchy-mac
  legacy-omarchy-mac  no Omarchy package, but omarchy-mac-keyring or a checkout's
                      omarchy-version on PATH
  reference           another distro on the Mac (Fedora Asahi Remix, Asahi ALARM, ...)

Only package names and versions, the os-release ID, the kinds of block devices
under the root filesystem and the image's candidate-set tag are read: never
device names, UUIDs or key slots.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .host import Host

OS_RELEASE = "/etc/os-release"
# The image-target manifest a converged image's builder writes; the first
# boot retires it to target.booted (omarchy-mac's install/helpers/image-target.sh).
# Its format ignores unknown keys, so a candidate image can name its set there
# (candidate_set=); the image builder doesn't yet, but it does write the set
# into the factory seal, which is on the root after a factory reset.
TARGET_RECORDS = ("/var/lib/omarchy/image/target", "/var/lib/omarchy/image/target.booted")
FACTORY_SEAL = "/var/lib/omarchy/factory-sealed"

STACK_PACKAGES = (
    "omarchy", "omarchy-dev", "omarchy-settings", "omarchy-settings-dev", "omarchy-mac", "omarchy-mac-boot", "omarchy-mac-keyring",
)
BOOT_PACKAGES = ("linux-aurora", "linux-asahi", "m1n1", "m1n1-aurora", "uboot-asahi", "limine")
# What Omarchy's hardware setup installs for the GPU and the speakers.
HARDWARE_PACKAGES = ("mesa", "vulkan-asahi", "asahi-audio", "speakersafetyd", "alsa-ucm-conf-asahi")
PACKAGES = STACK_PACKAGES + BOOT_PACKAGES + HARDWARE_PACKAGES
PACKAGE_QUERY = ["pacman", "-Q", *PACKAGES]
OMARCHY_VERSION = ["omarchy-version"]
ROOT_SOURCE = ["findmnt", "--noheadings", "--output", "SOURCE", "/"]

STACK_WORDS = {
    "converged": "Omarchy, converged image",
    "mx-mac": "Omarchy, mx-mac",
    "legacy-omarchy-mac": "Omarchy, legacy omarchy-mac",
    "reference": "reference run",
}

_TAG = re.compile(r"[A-Za-z0-9._-]{1,128}")
_DISTRO = re.compile(r"[a-z0-9][a-z0-9._-]{0,39}")


@dataclass(frozen=True)
class System:
    stack: str
    distro: str
    packages: dict[str, str]  # installed package -> version, in PACKAGES order
    has_pacman: bool
    candidate_set: str | None
    encryption: str  # on, off or unknown
    root_chain: tuple[str, ...]  # "TYPE FSTYPE" from the root filesystem down to its disk

    @property
    def is_omarchy(self) -> bool:
        return self.stack != "reference"

    def describe(self) -> str:
        words = STACK_WORDS[self.stack]
        if self.stack == "reference":
            words += f" on {self.distro}"
        if self.candidate_set:
            words += f", candidate set {self.candidate_set}"
        return words

    def report(self, boot_loader: str) -> dict:
        block = {
            "stack": self.stack,
            "distro": self.distro,
            "boot_loader": boot_loader,
            "encryption": self.encryption,
            "packages": [{"name": name, "version": version} for name, version in self.packages.items()],
        }
        if self.candidate_set:
            block["candidate_set"] = self.candidate_set
        return block


def detect(host: Host) -> System:
    query = host.run(PACKAGE_QUERY)
    has_pacman = query.returncode != 127
    installed = {}
    for line in query.stdout.splitlines() if has_pacman else []:
        parts = line.split()
        if len(parts) == 2 and parts[0] in PACKAGES:
            installed[parts[0]] = parts[1]
    packages = {name: installed[name] for name in PACKAGES if name in installed}

    if "omarchy-mac" in packages or "omarchy" in packages:
        stack = "converged"
    elif "omarchy-dev" in packages:
        stack = "mx-mac"
    elif "omarchy-mac-keyring" in packages or host.run(OMARCHY_VERSION).returncode == 0:
        stack = "legacy-omarchy-mac"
    else:
        stack = "reference"

    chain = _root_chain(host)
    if chain is None:
        encryption = "unknown"
    elif any(line.split()[0] == "crypt" or "crypto_LUKS" in line.split()[1:] for line in chain):
        encryption = "on"
    else:
        encryption = "off"

    return System(
        stack=stack,
        distro=_distro(host),
        packages=packages,
        has_pacman=has_pacman,
        candidate_set=_candidate_set(host),
        encryption=encryption,
        root_chain=tuple(chain or ()),
    )


def _key_values(host: Host, path: str) -> dict[str, str] | None:
    try:
        text = host.read_file(path).decode("utf-8", "replace")
    except OSError:
        return None
    values = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            values[key.strip()] = value.strip().strip("\"'")
    return values


def _distro(host: Host) -> str:
    distro = (_key_values(host, OS_RELEASE) or {}).get("ID", "").lower()
    return distro if _DISTRO.fullmatch(distro) else "unknown"


def _candidate_set(host: Host) -> str | None:
    """The candidate set a candidate image was built from, if its target record is present."""
    target = next((values for path in TARGET_RECORDS if (values := _key_values(host, path)) is not None), None)
    if target is None:
        return None
    tag = target.get("candidate_set") or (_key_values(host, FACTORY_SEAL) or {}).get("candidate_set")
    return tag if tag and _TAG.fullmatch(tag) else None


def _root_chain(host: Host) -> list[str] | None:
    """Block device types under the root filesystem, e.g. ["crypt btrfs", "part crypto_LUKS", "disk"]."""
    source = host.run(ROOT_SOURCE)
    device = source.stdout.strip().splitlines()[0].split("[")[0] if source.returncode == 0 and source.stdout.strip() else ""
    if not device.startswith("/dev/"):
        return None
    chain = host.run(["lsblk", "--noheadings", "--inverse", "--raw", "--output", "TYPE,FSTYPE", device])
    lines = [" ".join(line.split()) for line in chain.stdout.splitlines() if line.strip()]
    return lines if chain.returncode == 0 and lines else None
