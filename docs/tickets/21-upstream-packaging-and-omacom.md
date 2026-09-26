# 21: Upstream packaging and move to omacom

**What to build:** After the quattro-upstream work lands in Omarchy, the tool ships inside the omarchy-mac package as `omarchy hardware test`, the generic framework (host boundary, report, upload, terminal UI) is offered upstream with platform modules (Apple first), and the repository moves to omacom. The one-line installer keeps working for mx-mac and legacy installs and reference distros.

**Blocked by:** 10, and quattro-upstream landing upstream

**Status:** ready-for-agent

Parent spec: maralcbr/omarchy-m-testing#1

- [ ] omarchy-mac packages the CLI, reached as `omarchy hardware test` through Omarchy's command router
- [ ] Framework split so platform modules plug in; upstream proposal prepared for the owner to submit
- [ ] Repository transferred to omacom; links and installer updated
- [ ] One-line installer still serves mx-mac, legacy and reference-distro users
