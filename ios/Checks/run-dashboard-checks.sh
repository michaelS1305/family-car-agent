#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
swift_bin="${SWIFT_BIN:-/home/micha/.local/share/swiftly/bin/swiftc}"
out=$(mktemp -d "${TMPDIR:-/tmp}/fca-dashboard-checks.XXXXXX")
trap 'rm -rf "$out"' EXIT
"$swift_bin" -swift-version 6 -warnings-as-errors \
  Sources/FamilyCarAgent/Chat/ChatCore.swift \
  Sources/FamilyCarAgent/Dashboard/DashboardCore.swift Checks/DashboardChecks.swift -o "$out/dashboard-checks"
"$out/dashboard-checks"
