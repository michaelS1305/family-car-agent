#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
out=$(mktemp -d "${TMPDIR:-/tmp}/fca-family-checks.XXXXXX")
trap 'rm -rf "$out"' EXIT
"${SWIFT_BIN:-/home/micha/.local/share/swiftly/bin/swiftc}" -swift-version 6 -warnings-as-errors \
 Sources/FamilyCarAgent/Config/AppEnvironment.swift Sources/FamilyCarAgent/Auth/AuthCore.swift \
 Sources/FamilyCarAgent/Chat/ChatCore.swift Sources/FamilyCarAgent/History/HistoryCore.swift Sources/FamilyCarAgent/Auth/AuthAPI.swift \
 Sources/FamilyCarAgent/Vehicles/VehiclesCore.swift Sources/FamilyCarAgent/Family/FamilyCore.swift Sources/FamilyCarAgent/Family/FamilyModel.swift \
 Checks/FamilyChecks.swift -o "$out/family-checks"
"$out/family-checks"
