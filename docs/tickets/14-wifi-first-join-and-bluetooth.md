# 14: Wi-Fi first join and Bluetooth

**What to build:** The tool checks that the Mac joins a 5 GHz network on the first try after the Wi-Fi driver starts, by reloading the driver and rejoining only when a guaranteed rejoin path exists, and walks the user through pairing a Bluetooth device.

**Blocked by:** 11

**Status:** ready-for-agent

Parent spec: maralcbr/omarchy-m-testing#1

- [ ] First-join test runs only with a rejoin path and never over a Wi-Fi SSH session; restores the original connection
- [ ] Result records join time and whether traffic (an address) arrived on the first join
- [ ] Bluetooth pairing prompt with human confirmation
- [ ] Seam A tests with the recorded first-join failure and a good first join
