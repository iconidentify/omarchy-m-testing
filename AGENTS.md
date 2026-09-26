# omarchy-m-testing

Hardware testing for Omarchy on Apple Silicon (M-series) Macs: the `omarchy-m-test` CLI (`cli/`) and the omarchy-m-testing.org site (`site/`), sharing one versioned report schema.

## Rules

- Commit as the owner: `git -c user.name="Marcelo Alcantara" -c user.email=maralc@gmail.com commit ...`.
- No AI attribution anywhere: no Co-Authored-By trailers, no "Generated with", no model names in commits, PRs, issues, code or docs.
- Privacy is a hard requirement: reports never carry serial numbers, MAC addresses, hostnames, usernames, Wi-Fi network names, IP addresses, disk identifiers, key slots or home-directory content.
- The CLI never reboots a machine and never touches disk encryption or boot files; every change it makes is restored.

## Agent skills

### Issue tracker

Specs and issues live in this repo's GitHub Issues (`gh` CLI); build tickets live locally in `docs/tickets/` and are deleted after the build. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` and `docs/adr/` at the repo root, created as terms and decisions settle. See `docs/agents/domain.md`.
