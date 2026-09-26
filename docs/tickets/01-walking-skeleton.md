# 01: Walking skeleton: one check end to end

**What to build:** A user on an Apple Silicon Mac runs `omarchy-m-test`, sees the disclaimer, presses Enter, and one automatic check runs (Mac model, chip and kernel). The CLI writes a report, shows it, and on confirmation uploads it to a locally running site, which stores it and shows it on a report page. On a non-Apple machine the CLI refuses to run. This is the thinnest complete path through CLI, report schema, upload API, storage and a page, with the test seams in place.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

Parent spec: maralcbr/omarchy-m-testing#1

- [ ] CLI in Python 3 using only the standard library; every machine/human interaction goes through a single host boundary (run command, read file, list directory, prompt)
- [ ] Disclaimer screen: Enter accepts, anything else exits without running; consent version recorded in the report
- [ ] Non-Apple hardware is refused with a clear message
- [ ] One automatic check (model, chip, kernel) produces a schema-v1 report; `--dry-run` never uploads; the exact report is shown before an upload prompt
- [ ] Shared, versioned report schema plus at least one golden report used by both CLI and site tests
- [ ] Rails 8 + Postgres site: versioned upload API validates against the schema, stores the report, returns report and deletion links; minimal report page
- [ ] Seam A test: CLI runs against a recorded host with scripted answers and its report matches the golden report; Seam B test: posting the golden report yields the expected stored report and page
- [ ] CI runs both test suites on every push
