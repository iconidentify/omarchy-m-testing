# 05: Feature catalogue v1 and classification

**What to build:** Every check result is explained against a versioned feature catalogue, so a user sees "works", "not yet supported by Aurora", "not yet supported by Asahi" or "unknown hardware" instead of a bare failure. The catalogue has three layers (Asahi hardware features, Aurora additions, Omarchy integration) with per-chip expected states, and results are matched against Aurora first, then Asahi.

**Blocked by:** 01

**Status:** ready-for-agent

Parent spec: maralcbr/omarchy-m-testing#1

- [x] Catalogue v1 as a versioned data file: each entry names its layer and, per chip generation, the Asahi status and version, the Aurora status and version, and the Omarchy status
- [x] Asahi layer seeded by parsing Asahi's published per-chip feature tables, with CC-BY-3.0 credit recorded
- [x] Aurora additions (DP-alt/USB4 displays, VRR, camera image processor, AOP) and Omarchy integration features (notch bar, clamshell, auto keyboard light, speaker protection, 5 GHz first join, first-boot hardware setup) entered
- [x] Classification engine matches Aurora first, then Asahi; never treats a missing human answer as a failure; every report records the catalogue version
- [x] CI job parses Asahi's tables and flags drift from the catalogue
- [x] Seam A tests cover each classification outcome
