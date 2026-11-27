#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
out=$(mktemp -d "${TMPDIR:-/tmp}/fca-deletion-checks.XXXXXX")
trap 'rm -rf "$out"' EXIT
"${SWIFT_BIN:-$(command -v swiftc)}" -swift-version 6 -warnings-as-errors \
 Sources/FamilyCarAgent/Auth/AccountDeletionCleanup.swift Checks/AccountDeletionChecks.swift -o "$out/checks"
"$out/checks"

python3 Checks/test-account-deletion.py

if [[ "$(uname -s)" == Darwin ]]; then
  "${SWIFT_BIN:-$(command -v swiftc)}" -swift-version 6 -warnings-as-errors -D FCA_DELETION_APPLE_CHECKS -lsqlite3 \
    Sources/FamilyCarAgent/Config/AppEnvironment.swift Sources/FamilyCarAgent/Auth/AuthCore.swift \
    Sources/FamilyCarAgent/Auth/AuthAPI.swift Sources/FamilyCarAgent/Chat/ChatCore.swift \
    Sources/FamilyCarAgent/Family/FamilyCore.swift Sources/FamilyCarAgent/Vehicles/VehiclesCore.swift \
    Sources/FamilyCarAgent/History/HistoryCore.swift Sources/FamilyCarAgent/OfflineEvents/VehicleEventQueue.swift \
    Sources/FamilyCarAgent/Auth/KeychainVault.swift Sources/FamilyCarAgent/Auth/AccountDeletionCleanup.swift \
    Checks/AccountDeletionAppleChecks.swift -o "$out/apple-checks"
  "$out/apple-checks"
else
  echo 'NOT RUN: Apple Keychain integration requires macOS; wired into the existing macOS iOS validation job'
fi
