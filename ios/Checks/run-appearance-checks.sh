#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
out=$(mktemp -d "${TMPDIR:-/tmp}/fca-appearance-checks.XXXXXX")
trap 'rm -rf "$out"' EXIT
"${SWIFT_BIN:-/home/micha/.local/share/swiftly/bin/swiftc}" -swift-version 6 -warnings-as-errors \
 Sources/FamilyCarAgent/Appearance/AppAppearance.swift Sources/FamilyCarAgent/Appearance/FCAColors.swift \
 Checks/AppearanceChecks.swift -o "$out/checks"
"$out/checks"
