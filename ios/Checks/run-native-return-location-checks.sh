#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
out=$(mktemp -d "${TMPDIR:-/tmp}/fca-native-return-location.XXXXXX")
trap 'rm -rf "$out"' EXIT
"${SWIFT_BIN:-swiftc}" -swift-version 6 -warnings-as-errors  \
 Sources/FamilyCarAgent/OfflineEvents/VehicleAppIntents.swift \
 Sources/FamilyCarAgent/OfflineEvents/ReturnLocationAcquisitionCore.swift \
 Sources/FamilyCarAgent/OfflineEvents/LocationPermissionGate.swift \
 Checks/NativeReturnLocationChecks.swift -o "$out/checks"
"$out/checks"
python3 Checks/test-native-return-location.py
