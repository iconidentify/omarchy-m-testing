#!/usr/bin/env bash
# End-to-end smoke test against production (or SITE=...):
#   1. install the latest release with the site's one-line installer
#   2. run it with --dry-run (on a machine that isn't an Apple Silicon Mac it
#      must refuse, run nothing and exit 2; on a Mac it writes the report)
#   3. upload a golden report, fetch its page, then delete it via its deletion link
# Needs curl, python3, ssh-keygen. Leaves nothing on the site.
set -euo pipefail

site="${SITE:-https://omarchy-m-testing.org}"
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
t="$(mktemp -d)"
trap 'rm -rf "$t"' EXIT
fail() { echo "FAIL: $*" >&2; exit 1; }

echo "== install from $site/install"
curl -fsSL "$site/install" | HOME="$t/home" XDG_DATA_HOME= bash
cli="$t/home/.local/bin/omarchy-m-test"
"$cli" --version

echo "== omarchy-m-test --dry-run"
set +e
(cd "$t" && printf '\n' | HOME="$t/home" "$cli" --dry-run) > "$t/run.log" 2>&1
status=$?
set -e
cat "$t/run.log"
if grep -q "only runs on Apple Silicon Macs" "$t/run.log"; then
  [[ $status == 2 ]] || fail "refusal exited $status, not 2"
else
  [[ $status == 0 && -f "$t/omarchy-m-test-report.json" ]] || fail "dry run exited $status without a report"
fi
grep -q "^Uploaded\. Your report" "$t/run.log" && fail "--dry-run uploaded something"

echo "== upload a golden report"
golden="${GOLDEN:-$repo/schema/golden/signed/m2-max-image2.json}"
code="$(curl -sS -o "$t/upload.json" -w '%{http_code}' -H 'Content-Type: application/json' -H 'Accept: application/json' \
  --data-binary "@$golden" "$site/api/v1/reports")"
[[ $code == 201 ]] || fail "upload answered $code: $(cat "$t/upload.json")"
read -r report_url deletion_url < <(python3 -c 'import json,sys; b=json.load(open(sys.argv[1])); print(b["report_url"], b["deletion_url"])' "$t/upload.json")
echo "report: $report_url"
curl -fsS -o /dev/null "$report_url" || fail "report page not reachable"

echo "== delete it via its deletion link"
jar="$t/cookies"
curl -fsS -c "$jar" -o "$t/deletion.html" "$deletion_url"
csrf="$(python3 -c 'import re,sys; print(re.search(r"name=\"authenticity_token\" value=\"([^\"]+)\"", open(sys.argv[1]).read()).group(1))' "$t/deletion.html")"
token="${deletion_url##*token=}"
curl -fsS -b "$jar" -o "$t/deleted.html" -X POST "${report_url}" \
  --data-urlencode "_method=delete" --data-urlencode "authenticity_token=$csrf" --data-urlencode "token=$token"
grep -q "Report deleted" "$t/deleted.html" || fail "deletion didn't confirm"
code="$(curl -sS -o /dev/null -w '%{http_code}' "$report_url")"
[[ $code == 404 ]] || fail "deleted report still answers $code"

echo "smoke ok: installed $("$cli" --version), dry run as expected, golden report uploaded and deleted"
