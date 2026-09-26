# 20: Regressions, Aurora support table and one-click issues

**What to build:** The site flags a regression when a feature that passed in a verified earlier run on the same model and stack now fails, publishes the canonical Aurora feature-support table per chip from tester-verified runs, and lets the admin open a prefilled GitHub issue on omacom/linux or omacom/omarchy-mac from any failure or gap with one click.

**Blocked by:** 05, 19

**Status:** ready-for-agent

Parent spec: maralcbr/omarchy-m-testing#1

- [ ] Regression classification only against a verified earlier pass on the same model and stack
- [ ] Aurora feature-support table per chip generation, from tester-verified runs, with sources
- [ ] One-click prefilled issue (title, body with linked reports, target repo by layer)
- [ ] Seam B tests for regressions, the table and issue prefill
