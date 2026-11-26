#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
out=$(mktemp -d "${TMPDIR:-/tmp}/fca-native-location-poc.XXXXXX")
trap 'rm -rf "$out"' EXIT
"${SWIFT_BIN:-swiftc}" -swift-version 6 -warnings-as-errors -D DEBUG \
 Sources/FamilyCarAgent/OfflineEvents/VehicleAppIntents.swift \
 Sources/FamilyCarAgent/OfflineEvents/NativeLocationPOCCore.swift \
 Checks/NativeLocationPOCChecks.swift -o "$out/checks"
"$out/checks"
# Even if DEBUG is accidentally combined with Production, no POC declarations survive.
"${SWIFT_BIN:-swiftc}" -swift-version 6 -D DEBUG -D FCA_PRODUCTION -dump-ast \
 Sources/FamilyCarAgent/OfflineEvents/NativeLocationPOCCore.swift > "$out/production-ast"
if grep -q 'class_decl.*NativeLocationPOCCore' "$out/production-ast"; then
  echo 'Production must not contain POC types' >&2; exit 1
fi
