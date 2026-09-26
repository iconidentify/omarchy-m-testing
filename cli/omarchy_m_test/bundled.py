"""Files that ship with the tool itself, never anything on the machine.

The feature catalogue sits next to the package in a release
(omarchy_m_test/catalogue.json) and at catalogue/catalogue.json in the
repository; Asahi's reference kernel config likewise
(omarchy_m_test/asahi-kernel/ and catalogue/asahi-kernel/). omarchy-mac's check scripts are vendored under
omarchy_m_test/vendor/omarchy-mac/ (see ORIGIN there); the real host runs them
by name (Host.run_bundled). This is the only module besides the hosts that
touches files (scripts/check_boundary.py allows it), and only these paths.
"""

from __future__ import annotations

import os

_PACKAGE = os.path.dirname(os.path.abspath(__file__))
CATALOGUE_PATHS = (
    os.path.join(_PACKAGE, "catalogue.json"),
    os.path.join(os.path.dirname(os.path.dirname(_PACKAGE)), "catalogue", "catalogue.json"),
)
ASAHI_KERNEL_DIRS = (
    os.path.join(_PACKAGE, "asahi-kernel"),
    os.path.join(os.path.dirname(os.path.dirname(_PACKAGE)), "catalogue", "asahi-kernel"),
)
ASAHI_KERNEL_FILES = ("source.json", "config")


VENDOR = os.path.join(_PACKAGE, "vendor", "omarchy-mac")
# Bundled script name -> file under VENDOR.
SCRIPTS = {
    "mac-check": "mac-check",
    "apple-audio-check": "apple-audio-check.sh",
    "apple-display-check": "apple-display-check.sh",
}


def script_path(name: str) -> str:
    """Where a bundled script is; FileNotFoundError if the tool was installed without it."""
    path = os.path.join(VENDOR, SCRIPTS[name])
    if not os.path.isfile(path):
        raise FileNotFoundError(f"{name} isn't installed next to omarchy-m-test")
    return path


def catalogue_text() -> bytes:
    """The bundled catalogue's bytes; FileNotFoundError if the tool was installed without it."""
    for path in CATALOGUE_PATHS:
        if os.path.isfile(path):
            with open(path, "rb") as f:
                return f.read()
    raise FileNotFoundError("the feature catalogue isn't installed next to omarchy-m-test")


def asahi_kernel_config() -> tuple[bytes, bytes]:
    """Asahi's pinned reference kernel config: (source.json, config); FileNotFoundError if not installed."""
    for base in ASAHI_KERNEL_DIRS:
        paths = [os.path.join(base, name) for name in ASAHI_KERNEL_FILES]
        if all(os.path.isfile(path) for path in paths):
            texts = []
            for path in paths:
                with open(path, "rb") as f:
                    texts.append(f.read())
            return texts[0], texts[1]
    raise FileNotFoundError("Asahi's reference kernel config isn't installed next to omarchy-m-test")
