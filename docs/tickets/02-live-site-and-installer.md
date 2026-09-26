# 02: Live on omarchy-m-testing.org with signed release and one-line installer

**What to build:** Anyone can run the one-line installer from omarchy-m-testing.org, which downloads the latest tagged CLI release, verifies its signature, and installs `omarchy-m-test`. Their uploads go to the production site on Railway, served over HTTPS at omarchy-m-testing.org. Before each run the CLI tells the user if a newer version exists.

**Blocked by:** 01

**Status:** ready-for-agent (needs the owner to run `railway login` on the build Mac first)

Parent spec: maralcbr/omarchy-m-testing#1

- [ ] Site and Postgres deployed on the owner's Railway account, auto-deploying from `main`
- [ ] Porkbun DNS: apex alias to Railway, `www` redirect; HTTPS certificate valid
- [ ] Tagged releases publish a signed CLI tarball; the signing public key is pinned in the installer and README
- [ ] The installer verifies the signature, installs under the user's local share directory and puts `omarchy-m-test` on the PATH; re-running upgrades in place
- [ ] The CLI checks for a newer release before each run and says so
- [ ] An end-to-end smoke test (install, run in `--dry-run`, upload a golden report) passes against production
