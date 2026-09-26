#!/usr/bin/env bash
# Install or upgrade omarchy-m-test, the hardware test for Omarchy on Apple Silicon Macs.
#
#   curl -fsSL https://omarchy-m-testing.org/install | bash
#
# Downloads the latest tagged release, verifies its signature against the
# release key pinned below (ssh-keygen -Y verify), installs it under
# ~/.local/share/omarchy-m-test and links ~/.local/bin/omarchy-m-test.
# Running it again upgrades in place. Nothing outside those two paths changes,
# and nothing needs root.
#
# OMARCHY_M_TEST_RELEASES overrides where the release is downloaded from; the
# signature is still checked against the pinned key.

# Everything runs inside main, so a download cut short never runs half a script.
main() {
  set -euo pipefail

  local releases="${OMARCHY_M_TEST_RELEASES:-https://github.com/maralcbr/omarchy-m-testing/releases/latest/download}"
  local signer="release@omarchy-m-testing.org"
  local namespace="omarchy-m-test-release"
  # The release signing public key. Also published in the README; they must match.
  local allowed_signer='release@omarchy-m-testing.org namespaces="omarchy-m-test-release" ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKHA9ywzf4hxAd5Ohzw8tRg5i2lxHAxp2mDV0PWi5o0u'

  local data="${XDG_DATA_HOME:-$HOME/.local/share}/omarchy-m-test"
  local bin_dir="$HOME/.local/bin"

  local tool
  for tool in curl tar gzip ssh-keygen python3; do
    if ! command -v "$tool" >/dev/null 2>&1; then
      echo "omarchy-m-test needs $tool, which isn't installed." >&2
      case "$tool" in
        ssh-keygen) echo "Install it with: sudo pacman -S openssh" >&2 ;;
        python3) echo "Install it with: sudo pacman -S python" >&2 ;;
      esac
      exit 1
    fi
  done

  # Global, not local: the EXIT trap runs after main has returned.
  OMARCHY_M_TEST_WORK="$(mktemp -d)"
  trap 'rm -rf "$OMARCHY_M_TEST_WORK"' EXIT
  local work="$OMARCHY_M_TEST_WORK"

  echo "Downloading the latest omarchy-m-test release..."
  curl -fsSL --proto '=https,file' -o "$work/omarchy-m-test.tar.gz" "$releases/omarchy-m-test.tar.gz"
  curl -fsSL --proto '=https,file' -o "$work/omarchy-m-test.tar.gz.sig" "$releases/omarchy-m-test.tar.gz.sig"

  printf '%s\n' "$allowed_signer" > "$work/allowed_signers"
  if ! ssh-keygen -Y verify -f "$work/allowed_signers" -I "$signer" -n "$namespace" \
      -s "$work/omarchy-m-test.tar.gz.sig" < "$work/omarchy-m-test.tar.gz" > "$work/verify.log" 2>&1; then
    echo "The download's signature doesn't match the omarchy-m-test release key. Nothing was installed." >&2
    sed 's/^/  /' "$work/verify.log" >&2
    exit 1
  fi
  echo "Signature verified."

  mkdir -p "$work/unpacked"
  tar -xzf "$work/omarchy-m-test.tar.gz" -C "$work/unpacked" --no-same-owner
  local new="$work/unpacked/omarchy-m-test"
  if [[ ! -x "$new/bin/omarchy-m-test" || ! -f "$new/VERSION" ]]; then
    echo "The release doesn't look like omarchy-m-test. Nothing was installed." >&2
    exit 1
  fi
  local version previous=""
  version="$(<"$new/VERSION")"
  [[ -f "$data/VERSION" ]] && previous="$(<"$data/VERSION")"

  # Swap the whole directory, so an upgrade never mixes two versions' files.
  mkdir -p "$(dirname "$data")" "$bin_dir"
  rm -rf "$data.new" "$data.old"
  cp -R "$new" "$data.new"
  [[ -e "$data" ]] && mv "$data" "$data.old"
  mv "$data.new" "$data"
  rm -rf "$data.old"
  ln -sfn "$data/bin/omarchy-m-test" "$bin_dir/omarchy-m-test"

  if [[ -n "$previous" && "$previous" != "$version" ]]; then
    echo "Upgraded omarchy-m-test $previous -> $version."
  elif [[ -n "$previous" ]]; then
    echo "Reinstalled omarchy-m-test $version."
  else
    echo "Installed omarchy-m-test $version."
  fi

  case ":$PATH:" in
    *":$bin_dir:"*) echo "Run it with: omarchy-m-test" ;;
    *) echo "Run it with: $bin_dir/omarchy-m-test (add $bin_dir to your PATH to type just omarchy-m-test)" ;;
  esac
}

main "$@"
