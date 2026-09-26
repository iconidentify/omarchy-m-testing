# 09: Machine signing keys

**What to build:** On its first run the CLI silently creates a per-machine signing key and signs every report with it; the user never sees or manages it. The site verifies signatures, groups reports by machine without identifying the user, and rate-limits per machine key. This is what later lets tester runs be trusted without extra steps for the tester.

**Blocked by:** 01

**Status:** ready-for-agent

Parent spec: maralcbr/omarchy-m-testing#1

- [ ] Key created on first run, stored with user-only permissions, reused on later runs; no prompt
- [ ] Every report carries the machine's public key and a signature over the report
- [ ] Site rejects reports with invalid signatures and rate-limits per key (and per IP)
- [ ] "Two or more distinct machines agree" in 08 counts distinct machine keys
- [ ] Seam A and B tests for signing, verification and rejection of tampered reports
