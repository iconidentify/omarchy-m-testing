"""Data files that ship with the tool itself, never anything on the machine.

The feature catalogue sits next to the package in a release
(omarchy_m_test/catalogue.json) and at catalogue/catalogue.json in the
repository. This is the only module besides the hosts that opens files
(scripts/check_boundary.py allows it), and it reads only these paths.
"""

from __future__ import annotations

import os

_PACKAGE = os.path.dirname(os.path.abspath(__file__))
CATALOGUE_PATHS = (
    os.path.join(_PACKAGE, "catalogue.json"),
    os.path.join(os.path.dirname(os.path.dirname(_PACKAGE)), "catalogue", "catalogue.json"),
)


def catalogue_text() -> bytes:
    """The bundled catalogue's bytes; FileNotFoundError if the tool was installed without it."""
    for path in CATALOGUE_PATHS:
        if os.path.isfile(path):
            with open(path, "rb") as f:
                return f.read()
    raise FileNotFoundError("the feature catalogue isn't installed next to omarchy-m-test")
