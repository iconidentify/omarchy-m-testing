#!/usr/bin/env bash
# Build the CLI release tarball: release/build.sh OUTDIR
#
# OUTDIR/omarchy-m-test.tar.gz unpacks to omarchy-m-test/ with bin/, the
# omarchy_m_test package (the feature catalogue bundled as
# omarchy_m_test/catalogue.json, Asahi's reference kernel config as
# omarchy_m_test/asahi-kernel/, omarchy-mac's check scripts under
# omarchy_m_test/vendor/, the on-screen video check under omarchy_m_test/testcard/) and VERSION. release/check.sh checks a built one. OUTDIR/VERSION is the version
# on its own, which the CLI's newer-release check reads. Signing happens
# separately (release.yml), so this runs anywhere with GNU tar.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
out="$(mkdir -p "$1" && cd "$1" && pwd)"
version="$(python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import omarchy_m_test as t; print(t.TOOL_VERSION)' "$repo/cli")"

stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
root="$stage/omarchy-m-test"
mkdir -p "$root/bin" "$root/omarchy_m_test"
install -m 0755 "$repo/cli/bin/omarchy-m-test" "$root/bin/omarchy-m-test"
install -m 0644 "$repo"/cli/omarchy_m_test/*.py "$root/omarchy_m_test/"
install -m 0644 "$repo/catalogue/catalogue.json" "$root/omarchy_m_test/catalogue.json"
mkdir -p "$root/omarchy_m_test/asahi-kernel"
install -m 0644 "$repo/catalogue/asahi-kernel/source.json" "$repo/catalogue/asahi-kernel/config" "$root/omarchy_m_test/asahi-kernel/"
# Vendored check scripts and the video test card script (omarchy_m_test/bundled.py runs them), modes kept.
(cd "$repo/cli/omarchy_m_test" && find vendor testcard -type f | sort | while read -r f; do
  install -D -m "$([[ -x $f ]] && echo 0755 || echo 0644)" "$f" "$root/omarchy_m_test/$f"
done)
printf '%s\n' "$version" > "$root/VERSION"

# Reproducible: fixed order, owners and times.
epoch="${SOURCE_DATE_EPOCH:-$(git -C "$repo" log -1 --format=%ct 2>/dev/null || echo 0)}"
tar --sort=name --owner=0 --group=0 --numeric-owner --mtime="@$epoch" -C "$stage" -cf - omarchy-m-test \
  | gzip -9n > "$out/omarchy-m-test.tar.gz"
printf '%s\n' "$version" > "$out/VERSION"
echo "built omarchy-m-test $version: $out/omarchy-m-test.tar.gz"
