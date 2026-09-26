#!/usr/bin/env bash
# Build the CLI release tarball: release/build.sh OUTDIR
#
# OUTDIR/omarchy-m-test.tar.gz unpacks to omarchy-m-test/ with bin/, the
# omarchy_m_test package (the feature catalogue bundled as
# omarchy_m_test/catalogue.json) and VERSION. OUTDIR/VERSION is the version
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
printf '%s\n' "$version" > "$root/VERSION"

# Reproducible: fixed order, owners and times.
epoch="${SOURCE_DATE_EPOCH:-$(git -C "$repo" log -1 --format=%ct 2>/dev/null || echo 0)}"
tar --sort=name --owner=0 --group=0 --numeric-owner --mtime="@$epoch" -C "$stage" -cf - omarchy-m-test \
  | gzip -9n > "$out/omarchy-m-test.tar.gz"
printf '%s\n' "$version" > "$out/VERSION"
echo "built omarchy-m-test $version: $out/omarchy-m-test.tar.gz"
