#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
out=$(mktemp -d "${TMPDIR:-/tmp}/fca-return-location.XXXXXX")
trap 'rm -rf "$out"' EXIT
"${SWIFT_BIN:-swiftc}" -swift-version 6 -warnings-as-errors \
  Sources/FamilyCarAgent/OfflineEvents/VehicleAppIntents.swift \
  Checks/ReturnLocationChecks.swift -o "$out/checks"
"$out/checks"
