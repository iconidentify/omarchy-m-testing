# 08: Site v0.1 pages

**What to build:** Visitors browse a compatibility matrix per Mac model and Omarchy stack/version, pages per model and per feature, a kernel-gap list and terminal-style report pages, all in Omarchy's design language. Community reports appear immediately but only colour the matrix once two or more different machines agree. Users delete their own reports with the deletion link; the admin hides or deletes any report; everything exports as JSON or CSV.

**Blocked by:** 01, 05

**Status:** ready-for-agent

Parent spec: maralcbr/omarchy-m-testing#1

- [ ] Matrix, per-model, per-feature, kernel-gap and report pages
- [ ] Omarchy branding and design language: dark, Tokyo Night palette, JetBrains Mono, terminal cards; colour code green works / yellow partial / red regression / blue expected missing / magenta unknown hardware / grey not tested
- [ ] Aggregation: community reports visible immediately, labelled; matrix colour only from two or more distinct machines agreeing (tester rule arrives in 19)
- [ ] Deletion link removes a report and its evidence completely
- [ ] JSON and CSV exports of all public data (CC0)
- [ ] Admin (secret token): hide or delete any report
- [ ] Upload API rejects outdated schema versions with an upgrade message and unknown check IDs, and rate-limits per IP
- [ ] Seam B tests for every page, rule and admin action using golden reports
