# 19: Tester sign-in and candidate gating

**What to build:** A tester signs in once from the CLI by entering a short code on GitHub; from then on, their machine's signed runs count as tester runs automatically. The admin manages an allowlist of tester GitHub handles. Tester runs get a badge, colour the matrix on their own, and feed a per-candidate-set view that shows whether a candidate image is ready for promotion.

**Blocked by:** 08, 09

**Status:** ready-for-agent (needs the owner's OK to create the GitHub OAuth app)

Parent spec: maralcbr/omarchy-m-testing#1

- [x] GitHub device-flow sign-in in the CLI using only the OAuth app's client ID; the site binds the handle to the machine key
- [x] Admin sign-in with GitHub replaces the admin token; admin manages the tester allowlist
- [x] Tester badge; matrix colours from tester runs even without a second machine
- [x] Candidate-set view: per candidate set, tester results per model and feature
- [x] Seam A and B tests for sign-in, binding, allowlist and gating
