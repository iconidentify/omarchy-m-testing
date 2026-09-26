# Build tickets

Tracer-bullet tickets for the build described in the spec (maralcbr/omarchy-m-testing#1). One file per ticket, numbered in dependency order (blockers first). Each file names its blockers; a ticket can start when every blocker is done.

Working rules:
- Tick acceptance criteria in the ticket file as they're met.
- A ticket is done when all its criteria are ticked and its work is merged to `main`.
- When the last ticket is done, delete this whole folder in one commit: the tickets are build scaffolding, and their history stays in git.

| # | Ticket | Blocked by |
|---|---|---|
| 01 | Walking skeleton: one check end to end | none |
| 02 | Live on omarchy-m-testing.org with signed release and one-line installer | 01 |
| 03 | Recorded-Mac corpus and privacy scrubber | 01 |
| 04 | Inventory and gap map | 01, 03 |
| 05 | Feature catalogue v1 and classification | 01 |
| 06 | Core automatic checks | 03, 05 |
| 07 | Omarchy-vibes terminal UI | 01 |
| 08 | Site v0.1 pages | 01, 05 |
| 09 | Machine signing keys | 01 |
| 10 | v0.1 dogfood on the M1 and M2 | 02, 04, 06, 07, 08, 09 |
| 11 | Interactive framework and safety | 07 |
| 12 | Audio and display checks | 06, 11 |
| 13 | On-screen video check | 11 |
| 14 | Wi-Fi first join and Bluetooth | 11 |
| 15 | Sleep, lid and clamshell | 11 |
| 16 | Camera, input and ports | 11 |
| 17 | Graphics and video benchmarks | 08, 11 |
| 18 | Power | 11, 15 |
| 19 | Tester sign-in and candidate gating | 08, 09 |
| 20 | Regressions, Aurora support table and one-click issues | 05, 19 |
| 21 | Upstream packaging and move to omacom | 10, quattro-upstream landing upstream |
