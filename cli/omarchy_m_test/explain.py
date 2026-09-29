"""Plain-words explanations of check results, and --explain for a saved report."""

from __future__ import annotations

import json

from .catalogue import Catalogue, CatalogueError, parse, status_label
from .host import Host
from . import bundled
from .system import build_words


def load_catalogue(host: Host, path: str | None) -> Catalogue:
    """The bundled catalogue, or a draft one the user names with --catalogue."""
    try:
        text = host.read_file(path) if path else bundled.catalogue_text()
    except OSError as error:
        raise CatalogueError(f"couldn't read it ({error})") from error
    return parse(text)


def line(check: dict, classification: dict, catalogue: Catalogue) -> str:
    """One result as the human sees it, e.g. "  PASS  system.identity  works (Device tree)"; a benchmark's with its
    score. A failure the catalogue expects reads GAP ("not yet supported by Asahi") or N/A, not FAIL."""
    feature = catalogue.feature_for_check(check["id"])
    name = feature["name"] if feature else classification["feature"]
    score = check.get("score")
    measured = f", score {score['value']} {score['unit']} ({score['tool']})" if isinstance(score, dict) else ""
    return f"  {status_label(check['status'], classification['outcome']):4}  {check['id']}  {catalogue.words(classification['outcome'])} ({name}){measured}"


def explain(host: Host, path: str, catalogue: Catalogue) -> bool:
    """Show a saved report's results explained against the catalogue. False if the report can't be read."""
    try:
        report = json.loads(host.read_file(path))
        machine, checks = report["machine"], report["checks"]
        soc, board, model = machine["soc"], machine["board"], machine["model"]
        results = [{"id": c["id"], "status": c["status"], **({"score": c["score"]} if isinstance(c.get("score"), dict) else {})} for c in checks]
    except OSError as error:
        host.show(f"Couldn't read {path} ({error}).")
        return False
    except (ValueError, KeyError, TypeError):
        host.show(f"{path} isn't an omarchy-m-test report.")
        return False

    used = report.get("catalogue_version")
    build = _build(report.get("system"))
    if build:
        host.show(f"{model}, build {build}")
    host.show(f"{model}: {len(results)} results explained with feature catalogue v{catalogue.version}"
              + (f" (the report was made with v{used})." if used not in (None, catalogue.version) else "."))
    for check in results:
        try:
            classification = catalogue.classify(check, soc, board)
        except CatalogueError:
            host.show(f"  {str(check['status']).upper():4}  {check['id']}  not in feature catalogue v{catalogue.version}")
            continue
        host.show(line(check, classification, catalogue))
    return True


def _build(system) -> str | None:
    """The build a saved report's run was on (system.build_words); None if it names none."""
    if not isinstance(system, dict) or not isinstance(system.get("packages"), list):
        return None
    packages = {p["name"]: p["version"] for p in system["packages"] if isinstance(p, dict) and isinstance(p.get("name"), str)
                and isinstance(p.get("version"), str)}
    if system.get("stack") == "reference":
        return None
    image = system.get("image") if isinstance(system.get("image"), dict) else {}
    candidate_set = system.get("candidate_set") or image.get("candidate_set")
    return build_words(packages, candidate_set if isinstance(candidate_set, str) else None,
                       image.get("built") if isinstance(image.get("built"), str) else None)
