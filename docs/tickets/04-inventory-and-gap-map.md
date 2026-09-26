# 04: Inventory and gap map

**What to build:** Every run maps the Mac's hardware: for each hardware node, its type, status and whether a driver claimed it; firmware-load failures and driver probe errors from the kernel log; and the kernel's build options compared with Asahi's. Hardware no driver claims shows up as "unknown hardware" in the report and on the report page, so unsupported hardware gets noticed.

**Blocked by:** 01, 03

**Status:** ready-for-agent

Parent spec: maralcbr/omarchy-m-testing#1

- [x] Inventory records only node type, status and driver-bound, never property values
- [x] Firmware-load failures and probe errors captured as scrubbed evidence
- [x] Kernel build options diffed against Asahi's reference configuration, reported as differences
- [x] Unclaimed hardware classified as "unknown hardware" and listed on the report page
- [x] Seam A tests with M1 and M2 recordings produce the expected inventory and unknown-hardware list
