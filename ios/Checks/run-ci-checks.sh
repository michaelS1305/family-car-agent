#!/usr/bin/env bash
# Standalone checks; no providers, accounts, device, signing or xtool required.
set -euo pipefail
cd "$(dirname "$0")/.."
export SWIFT_BIN="${SWIFT_BIN:-$(command -v swiftc)}"
out=$(mktemp -d "${TMPDIR:-/tmp}/fca-ios-ci.XXXXXX")
trap 'rm -rf "$out"' EXIT
bash Checks/run-auth-checks.sh
python3 Checks/check-entry-resources.py
base=(Sources/FamilyCarAgent/Config/AppEnvironment.swift
      Sources/FamilyCarAgent/Auth/AuthCore.swift
      Sources/FamilyCarAgent/Auth/AuthAPI.swift)
for mode in debug release; do
  # Keep the array nonempty for macOS's Bash 3.2 with nounset enabled.
  flags=(-Onone)
  if [[ "$mode" == debug ]]; then flags=(-Onone -D DEBUG); fi
  for check in AppleAuthDiagnosticsCheck GoogleAuthDiagnosticsCheck; do
    "$SWIFT_BIN" "${flags[@]}" -swift-version 6 -warnings-as-errors \
      "${base[@]}" "Checks/$check.swift" -o "$out/$check-$mode"
    "$out/$check-$mode" > "$out/$check-$mode.log"
    # Never print captured diagnostics on failure, only a fixed explanation.
    if grep -q 'PRIVATE_.*SENTINEL' "$out/$check-$mode.log"; then
      echo 'FAIL: synthetic confidential value reached diagnostic output'; exit 1
    fi
    if [[ "$mode" == release ]] && LC_ALL=C grep -aEq 'FCA_(APPLE|GOOGLE)_AUTH_DIAG' "$out/$check-$mode"; then
      echo 'FAIL: diagnostic marker exists in Release check'; exit 1
    fi
    echo "PASS: $check ($mode)"
  done
done
"$SWIFT_BIN" -D DEBUG -swift-version 6 -warnings-as-errors "${base[@]}" \
  Sources/FamilyCarAgent/Auth/OnboardingValidation.swift \
  Sources/FamilyCarAgent/Auth/EntryModel.swift \
  Checks/EntryChecks.swift Checks/EntryUIChecks.swift Checks/AuthCheck.swift \
  -o "$out/auth-debug"
"$out/auth-debug" > "$out/auth-debug.log"
echo 'PASS: DEBUG authentication and route checks'
