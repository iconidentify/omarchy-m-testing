"""The feature catalogue (catalogue/catalogue.json) and result classification.

The catalogue says, per feature and chip generation, what each layer
expects: Asahi's published state, Aurora's and Omarchy's. A check result is
explained against it: Aurora's expected state first, then Asahi's.

Outcomes:
  works             the check passed
  fails             it failed where Aurora (and Omarchy, for integration
                    features) expects it to work; the site upgrades this to a
                    regression only against a verified earlier pass
  not-in-aurora     Asahi supports it (or it's an Aurora addition) and Aurora doesn't yet
  not-in-asahi      Asahi doesn't support it yet, so neither does Aurora
  not-in-omarchy    the kernel supports it but Omarchy's integration doesn't yet
  not-applicable    this Mac doesn't have the hardware
  unknown-hardware  the chip, or this feature on it, isn't in the catalogue
  not-tested        skipped; a missing human answer is never a failure
"""

from __future__ import annotations

import json
from dataclasses import dataclass

LAYERS = ("asahi", "aurora", "omarchy")
STATUSES = {
    "asahi": {"upstream", "linux-asahi", "yes", "wip", "tba", "no", "out-of-tree", "see-notes", "absent"},
    "aurora": {"supported", "asahi", "unsupported", "unknown", "absent"},
    "omarchy": {"supported", "unsupported", "absent"},
}
ASAHI_SUPPORTED = {"upstream", "linux-asahi", "yes"}
OUTCOMES = (
    "works", "fails", "not-in-aurora", "not-in-asahi", "not-in-omarchy",
    "not-applicable", "unknown-hardware", "not-tested",
)


class CatalogueError(Exception):
    """The catalogue file is missing, not JSON or not shaped as expected."""


@dataclass(frozen=True)
class Catalogue:
    data: dict

    @property
    def version(self) -> int:
        return self.data["catalogue_version"]

    def words(self, outcome: str) -> str:
        return self.data["outcomes"][outcome]

    def feature_for_check(self, check_id: str) -> dict | None:
        feature_id = self.data["checks"].get(check_id)
        return self._features.get(feature_id) if feature_id else None

    def chip_for_soc(self, soc: str) -> str | None:
        return next((chip for chip, info in self.data["chips"].items() if soc in info["socs"]), None)

    @property
    def _features(self) -> dict[str, dict]:
        return {f["id"]: f for f in self.data["features"]}

    def expected(self, feature: dict, chip: str | None, board: str) -> dict[str, dict] | None:
        """Each layer's expected state for this chip and board; None if the catalogue doesn't cover it."""
        if chip is None or chip not in feature["chips"]:
            return None
        states = dict(feature["chips"][chip])
        states.update(feature.get("models", {}).get(board, {}))
        if "asahi" not in states and feature.get("asahi_feature"):
            linked = self.expected(self._features[feature["asahi_feature"]], chip, board)
            if linked and "asahi" in linked:
                states["asahi"] = linked["asahi"]
        return states

    def classify(self, check: dict, soc: str, board: str) -> dict:
        """The classification of one schema-v1 check result on a machine with this SoC and board."""
        feature = self.feature_for_check(check["id"])
        if feature is None:
            raise CatalogueError(f"check {check['id']!r} isn't in catalogue v{self.version}")
        states = self.expected(feature, self.chip_for_soc(soc), board)
        result = {
            "outcome": _outcome(check["status"], feature["layer"], states),
            "feature": feature["id"],
            "layer": feature["layer"],
            "expected": {layer: states[layer]["status"] for layer in LAYERS if states and layer in states},
        }
        return result


def _outcome(status: str, layer: str, states: dict | None) -> str:
    if status == "skip":
        return "not-tested"
    if status == "pass":
        return "works"
    if states is None:
        return "unknown-hardware"

    asahi = states.get("asahi", {}).get("status", "unlisted")
    aurora = states.get("aurora", {}).get("status", "unknown")
    omarchy = states.get("omarchy", {}).get("status")
    if "absent" in (asahi, aurora, omarchy):
        return "not-applicable"
    omarchy_missing = layer == "omarchy" and omarchy != "supported"

    # Aurora first: does the kernel Omarchy runs expect this to work?
    if aurora == "supported" or (aurora == "asahi" and asahi in ASAHI_SUPPORTED):
        return "not-in-omarchy" if omarchy_missing else "fails"
    # Then Asahi: Aurora lacks something Asahi has, or Asahi doesn't have it either.
    if asahi in ASAHI_SUPPORTED:
        return "not-in-aurora"
    if asahi == "unlisted":  # an Aurora addition or an Omarchy feature Asahi doesn't track
        return "not-in-omarchy" if omarchy_missing else "not-in-aurora"
    return "not-in-asahi"


def parse(text: str | bytes) -> Catalogue:
    """Parse and check a catalogue; raises CatalogueError with the first problem found."""
    try:
        data = json.loads(text)
    except ValueError as error:
        raise CatalogueError(f"not valid JSON ({error})") from error
    _check(data)
    return Catalogue(data)


def _require(condition: bool, problem: str) -> None:
    if not condition:
        raise CatalogueError(problem)


def _check_states(where: str, states: object, layer: str) -> None:
    _require(isinstance(states, dict), f"{where}: expected an object")
    for name, state in states.items():
        _require(name in LAYERS, f"{where}: unknown layer {name!r}")
        _require(isinstance(state, dict) and state.get("status") in STATUSES[name],
                 f"{where}.{name}: status must be one of {sorted(STATUSES[name])}")
    if layer == "asahi":
        _require("omarchy" not in states, f"{where}: Asahi features carry no Omarchy state")


def _check(data: object) -> None:
    _require(isinstance(data, dict), "the catalogue must be an object")
    version = data.get("catalogue_version")
    _require(isinstance(version, int) and not isinstance(version, bool) and version >= 1,
             "catalogue_version must be a positive integer")
    _require(isinstance(data.get("outcomes"), dict) and set(data["outcomes"]) == set(OUTCOMES),
             f"outcomes must word exactly {list(OUTCOMES)}")
    chips = data.get("chips")
    _require(isinstance(chips, dict) and chips, "chips must be a non-empty object")
    for chip, info in chips.items():
        _require(isinstance(info, dict) and isinstance(info.get("socs"), list) and isinstance(info.get("name"), str),
                 f"chips.{chip}: needs a name and a list of socs")
    features = data.get("features")
    _require(isinstance(features, list), "features must be a list")
    ids = {}
    for index, feature in enumerate(features):
        where = f"features[{index}]"
        _require(isinstance(feature, dict) and isinstance(feature.get("id"), str) and isinstance(feature.get("name"), str),
                 f"{where}: needs an id and a name")
        where = f"feature {feature['id']}"
        _require(feature["id"] not in ids, f"{where}: listed twice")
        _require(feature.get("layer") in LAYERS, f"{where}: layer must be one of {list(LAYERS)}")
        ids[feature["id"]] = feature
        _require(isinstance(feature.get("chips"), dict), f"{where}: chips must be an object")
        for chip, states in feature["chips"].items():
            _require(chip in chips, f"{where}: unknown chip {chip!r}")
            _check_states(f"{where}.{chip}", states, feature["layer"])
            if feature["layer"] == "asahi":
                _require("asahi" in states, f"{where}.{chip}: an Asahi feature needs its Asahi state")
            if feature["layer"] == "omarchy":
                _require("omarchy" in states, f"{where}.{chip}: an Omarchy feature needs its Omarchy state")
        for board, states in feature.get("models", {}).items():
            _check_states(f"{where}.models.{board}", states, feature["layer"])
    for feature in features:
        link = feature.get("asahi_feature")
        if link is not None:
            _require(feature["layer"] != "asahi", f"feature {feature['id']}: Asahi features can't link to another")
            _require(ids.get(link, {}).get("layer") == "asahi",
                     f"feature {feature['id']}: asahi_feature {link!r} isn't an Asahi feature")
    checks = data.get("checks")
    _require(isinstance(checks, dict), "checks must be an object")
    for check_id, feature_id in checks.items():
        _require(feature_id in ids, f"check {check_id}: unknown feature {feature_id!r}")
