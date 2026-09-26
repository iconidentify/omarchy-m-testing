#!/usr/bin/env bash
# Test the installer against a locally built release signed with a throwaway
# key: a fresh install, an upgrade in place, and a tampered download that
# must be refused. Runs in CI (and in an Arch container) with GNU tar.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
t="$(mktemp -d)"
trap 'rm -rf "$t"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

ssh-keygen -q -t ed25519 -N '' -C test -f "$t/key"
pub="$(cut -d' ' -f1,2 "$t/key.pub")"
# The installer under test, with the throwaway key pinned in place of the real one.
sed -E "s|(local allowed_signer='[^ ]+ namespaces=\"[^\"]+\" )ssh-ed25519 [A-Za-z0-9+/=]+'|\\1$pub'|" \
  "$repo/installer/install.sh" > "$t/install.sh"
grep -q "$pub" "$t/install.sh" || fail "couldn't pin the test key in the installer"

release() { # release DIR: build and sign the current tree into DIR
  "$repo/release/build.sh" "$1" >/dev/null
  ssh-keygen -q -Y sign -f "$t/key" -n omarchy-m-test-release "$1/omarchy-m-test.tar.gz"
}
install_from() { HOME="$t/home" XDG_DATA_HOME= PATH="$t/home/.local/bin:$PATH" OMARCHY_M_TEST_RELEASES="file://$1" bash "$t/install.sh"; }

release "$t/r1"
out="$(install_from "$t/r1")"
grep -q "Installed omarchy-m-test" <<<"$out" || fail "fresh install: $out"
"$t/home/.local/bin/omarchy-m-test" --version | grep -q "omarchy-m-test $(<"$t/r1/VERSION")" || fail "installed CLI doesn't run"
[[ -f "$t/home/.local/share/omarchy-m-test/omarchy_m_test/catalogue.json" ]] || fail "catalogue not bundled"

# Upgrade in place: a stray file from the old version must not survive.
touch "$t/home/.local/share/omarchy-m-test/stray"
out="$(install_from "$t/r1")"
grep -q "Reinstalled" <<<"$out" || fail "re-run: $out"
[[ ! -e "$t/home/.local/share/omarchy-m-test/stray" ]] || fail "upgrade kept old files"
echo "9.9.9" > "$t/home/.local/share/omarchy-m-test/VERSION"
out="$(install_from "$t/r1")"
grep -q "Upgraded omarchy-m-test 9.9.9 -> " <<<"$out" || fail "upgrade message: $out"

# A tarball that doesn't match its signature is refused and changes nothing.
mkdir "$t/bad" && cp "$t/r1"/* "$t/bad/"
printf 'x' >> "$t/bad/omarchy-m-test.tar.gz"
before="$(ls -la "$t/home/.local/share/omarchy-m-test")"
if out="$(install_from "$t/bad" 2>&1)"; then fail "tampered release was installed"; fi
grep -q "signature doesn't match" <<<"$out" || fail "tampered: $out"
[[ "$before" == "$(ls -la "$t/home/.local/share/omarchy-m-test")" ]] || fail "tampered release changed the install"

# A release signed by some other key is refused too.
ssh-keygen -q -t ed25519 -N '' -C other -f "$t/other"
mkdir "$t/other-r" && cp "$t/r1/omarchy-m-test.tar.gz" "$t/other-r/"
ssh-keygen -q -Y sign -f "$t/other" -n omarchy-m-test-release "$t/other-r/omarchy-m-test.tar.gz"
if install_from "$t/other-r" >/dev/null 2>&1; then fail "release signed by another key was installed"; fi

echo "installer ok"
